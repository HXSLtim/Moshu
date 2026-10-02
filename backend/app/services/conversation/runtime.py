"""创作对话 Agent 运行时：LangGraph 状态图 + 流式输出。

模型通过 tools 主动提出设定写入或正文草稿；提案工具只登记提案，不写数据库，
作者确认后才由前端调用既有命令接口落库。只读工具让模型主动查阅账本、
简介、大纲与旧正文，自查工具让模型在交稿前用确定性校验核对草稿。
这样既是真正的工具调用，又不破坏"AI 操作可审阅"的项目原则。

编排由 LangGraph 的 StateGraph 承担：``agent`` 节点流式调用模型并累积工具请求，
``tools`` 节点执行工具，条件边在还有工具请求时回到 ``agent``。工具的重复调用去重、
只读工具不可用时的显式声明，以及作者身份/生命周期错误向上终止，都在工具节点内
按项目既有语义实现，不因换成图编排而放宽。
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import suppress
from typing import Annotated, AsyncIterator, TypedDict

from langchain_core.messages import AIMessage, ToolMessage, convert_to_messages
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode as _LangGraphToolNode
from loguru import logger

from app.services.conversation.tools import CHECK_TOOL_NAME, READ_TOOL_NAMES, READ_TOOL_SPECS
from app.services.conversation.capability_tools import CAPABILITY_TOOL_NAMES, CAPABILITY_TOOL_SPECS
from app.services.context.budget import MAX_CHAT_OUTPUT_CHARS, MAX_TRACE_PREVIEW_CHARS, compact_text
from app.services.context.builder import ContextScopeError
from app.services.model.result import parse_model_result
from app.services.model.execution import record_stream_usage, stream_model


PROPOSE_TOOLS: list[dict] = [
    {
        'type': 'function',
        'function': {
            'name': 'propose_project_info',
            'description': '提议更新项目信息（类型、简介、世界观）。只在作者这次确实给出或修改了这些内容时调用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'genre': {'type': 'string', 'description': '小说类型，未涉及就不要传'},
                    'description': {'type': 'string', 'description': '小说简介，未涉及就不要传'},
                    'worldview': {'type': 'string', 'description': '完整世界观文本，未涉及就不要传'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_entity',
            'description': '提议新增需要长期跟踪的人物、物品、地点或组织。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'entity_kind': {'type': 'string', 'enum': ['character', 'item', 'location', 'organization']},
                    'description': {'type': 'string', 'description': '一句话说明这个实体'},
                },
                'required': ['name', 'entity_kind', 'description'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_fact',
            'description': '提议记录一条可核对的设定事实，例如人物身份、位置、持有物、关系或世界规则。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'subject': {'type': 'string'},
                    'attribute': {'type': 'string'},
                    'value': {'type': 'string'},
                },
                'required': ['subject', 'attribute', 'value'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_outline',
            'description': '提议补一条卷、阶段或章节的计划大纲。计划不代表已经发生。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'node_kind': {'type': 'string', 'enum': ['volume', 'chapter']},
                    'title': {'type': 'string'},
                    'chapter_number': {'type': 'integer', 'description': '章节号，写卷时不要传'},
                    'summary': {'type': 'string'},
                },
                'required': ['node_kind', 'title', 'summary'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_manuscript',
            'description': '作者让你接着写、改写本章或开新章时，提交完整正文稿件。不要用它回答普通问题。'
                           '正文的唯一交付通道：不要把草稿写进对话回复。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'operation': {'type': 'string', 'enum': ['append', 'rewrite', 'create']},
                    'content': {'type': 'string', 'description': '完整可用的正文，不要写占位或省略'},
                    'title': {'type': 'string', 'description': '仅开新章时给出章节标题'},
                    'uncertainties': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '本次创作中你不确定、替作者做过的假设，最多 12 条；没有就省略',
                    },
                },
                'required': ['operation', 'content'],
            },
        },
    },
]

AGENT_TOOLS: list[dict] = PROPOSE_TOOLS + READ_TOOL_SPECS + CAPABILITY_TOOL_SPECS

SETTING_TOOLS = {'propose_project_info', 'propose_entity', 'propose_fact', 'propose_outline'}
_OPERATION = {'append': 'append', 'rewrite': 'replace', 'create': 'create'}
_MODE = {'append': 'continue', 'rewrite': 'rewrite', 'create': 'new_chapter'}

TOOLS_UNAVAILABLE_ACK = '本轮没有检索工具可用，请基于已有上下文回答，并说明该信息未能核实。'
DUPLICATE_CALL_ACK = '重复调用已忽略。'


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def execute_agent_tool(name: str, raw_args) -> tuple[dict | None, dict | None, str]:
    """执行一次工具调用。

    返回 ``(action, manuscript, ack)``；action 是待作者确认的设定提案，
    manuscript 是待确认的正文稿件。这里不接触数据库。
    """
    args = _args(raw_args)
    if name == 'propose_project_info':
        action = {'kind': 'project_info', 'genre': args.get('genre'), 'description': args.get('description'),
                  'worldview': args.get('worldview')}
        if not any(action[key] for key in ('genre', 'description', 'worldview')):
            return None, None, '没有可用字段，未登记提案。'
        return action, None, '已登记项目信息提案，等待作者确认。'
    if name == 'propose_entity':
        if not args.get('name') or args.get('entity_kind') not in {'character', 'item', 'location', 'organization'}:
            return None, None, '缺少名称或类型不合法，未登记提案。'
        return ({'kind': 'entity', 'name': str(args['name']), 'entity_kind': args['entity_kind'],
                 'description': str(args.get('description') or '')}, None, '已登记实体提案，等待作者确认。')
    if name == 'propose_fact':
        if not args.get('subject') or not args.get('attribute') or not args.get('value'):
            return None, None, '缺少主体、属性或值，未登记提案。'
        return ({'kind': 'fact', 'subject': str(args['subject']), 'attribute': str(args['attribute']),
                 'value': str(args['value'])}, None, '已登记设定事实提案，等待作者确认。')
    if name == 'propose_outline':
        if args.get('node_kind') not in {'volume', 'chapter'} or not args.get('title'):
            return None, None, '大纲类型或标题不合法，未登记提案。'
        number = args.get('chapter_number')
        if args['node_kind'] == 'chapter' and (not isinstance(number, int) or isinstance(number, bool) or number <= 0):
            return None, None, '章节大纲缺少合法章节号，未登记提案。'
        return ({'kind': 'outline', 'node_kind': args['node_kind'], 'title': str(args['title']),
                 'chapter_number': number if args['node_kind'] == 'chapter' else None,
                 'summary': str(args.get('summary') or '')}, None, '已登记大纲提案，等待作者确认。')
    if name == 'write_manuscript':
        if args.get('operation') not in _OPERATION or not str(args.get('content') or '').strip():
            return None, None, '稿件不完整，未登记。'
        uncertainties = [str(item).strip()[:500] for item in (args.get('uncertainties') or [])
                         if isinstance(item, str) and item.strip()][:12]
        manuscript = {'operation': args['operation'], 'content': str(args['content']).strip(),
                      'title': str(args['title']).strip() if args.get('title') else None,
                      'uncertainties': uncertainties}
        return None, manuscript, '已收到正文稿件，等待作者采纳。'
    return None, None, f'未实现的工具：{name}'

# ========== LangGraph 编排 ==========

class _AgentState(TypedDict):
    """图状态：消息累积使用 add_messages，与 LangGraph 预置 Agent 的状态约定一致。"""
    messages: Annotated[list, add_messages]


class AgentTrace:
    """本轮工具调用产生的提案与稿件，供图节点与最终结果共享。"""

    def __init__(self) -> None:
        self.actions: list[dict] = []
        self.manuscript: dict | None = None


async def _execute_tool(name: str, raw_args, *, read_tool_executor, capability_tool_executor,
                        seen: set[str], trace: AgentTrace, publish: object, manuscript_ack=None):
    """执行一次工具调用。

    返回 ``(ack, event)``：ack 是回填给模型的确认文本，event 是给前端的观察事件。
    作者身份或生命周期错误必须向上抛出，不能降级为无界检索。
    ``manuscript_ack`` 是 ``(manuscript) -> str`` 的稿件回执生成器,由调用方
    提供真实落点(章号)说明;缺失时退回不含章号的通用回执。
    """
    name = name or ''
    signature = f'{name}:{json.dumps(_args(raw_args), ensure_ascii=False, sort_keys=True)}'
    if signature in seen:
        return DUPLICATE_CALL_ACK, None
    seen.add(signature)

    if name in READ_TOOL_NAMES:
        if read_tool_executor is None:
            return TOOLS_UNAVAILABLE_ACK, None
        try:
            result = await read_tool_executor(name, _args(raw_args))
        except ContextScopeError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning('Agent 只读工具 {} 执行失败：{}', name, exc)
            result = '检索工具暂时不可用，请基于已有上下文回答，并说明该信息未能核实。'
        status = 'checked' if name == CHECK_TOOL_NAME else 'read'
        return result, {'type': 'tool', 'name': name, 'status': status,
                        'data': {'summary': compact_text(result, MAX_TRACE_PREVIEW_CHARS, keep='head')}}
    if name in CAPABILITY_TOOL_NAMES:
        if capability_tool_executor is None:
            return TOOLS_UNAVAILABLE_ACK, None
        # 能力工具先发 running 事件,长任务(编排/续写)期间前端有可感知进度。
        await publish({'type': 'tool', 'name': name, 'status': 'running',
                       'data': {'summary': compact_text(_args(raw_args).get('instruction')
                                                        or _args(raw_args).get('query') or '', 60, keep='head')}})
        try:
            result = await capability_tool_executor(name, _args(raw_args))
        except ContextScopeError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning('Agent 能力工具 {} 执行失败：{}', name, exc)
            result = f'工具 {name} 执行失败,请向作者说明。'
        return result, {'type': 'tool', 'name': name, 'status': 'completed',
                        'data': {'summary': compact_text(result, MAX_TRACE_PREVIEW_CHARS, keep='head')}}

    action, draft, ack = execute_agent_tool(name, raw_args)
    if action is not None:
        trace.actions.append(action)
        return ack, {'type': 'tool', 'name': name, 'status': 'proposed', 'data': action}
    if draft is not None:
        trace.manuscript = draft
        if manuscript_ack is not None:
            # 回执明示真实落点(章号),让模型的章号自我认知与章节表对齐。
            try:
                ack = manuscript_ack(draft)
            except Exception as exc:  # noqa: BLE001
                logger.warning('稿件回执生成失败,退回通用回执: {}', exc)
        return ack, {'type': 'tool', 'name': name, 'status': 'drafted', 'data': draft}
    return ack, None


def _params_model(name: str, parameters: dict):
    """按既有 function 规格生成参数模型，保证工具面与模型看到的一致。

    自由签名的 ``**kwargs`` 包装会让 LangChain 推断出空参数表，
    模型给出的实参会在此前的校验里被丢掉，所以参数必须显式声明。
    """
    from pydantic import create_model

    types = {'string': str, 'integer': int, 'number': float, 'boolean': bool}

    def _annotation(spec: dict):
        # 数组参数必须显式映射，否则实参会被参数表校验静默丢弃。
        if spec.get('type') == 'array':
            return list[str] if (spec.get('items') or {}).get('type') == 'string' else list
        return types.get(spec.get('type'), str)

    properties = parameters.get('properties') or {}
    required = set(parameters.get('required') or [])
    fields = {}
    for key, spec in properties.items():
        annotation = _annotation(spec)
        description = spec.get('description')
        if key in required:
            fields[key] = (annotation, ...)
        else:
            fields[key] = (annotation | None, None)
    return create_model(f'{name}_args', **fields)


def _recording_tools(*, read_tool_executor, capability_tool_executor, seen: set[str], trace: AgentTrace, publish,
                     manuscript_ack=None):
    """构造 LangGraph 工具节点：执行工具、回填 ToolMessage，并把观察事件推给前端。

    提案工具仍然只登记提案，不触碰数据库；工具节点只把结果交回模型。
    工具声明沿用既有 function 规格，因此模型看到的工具面没有变化。
    """

    def make_runner(name: str):
        async def _run(**kwargs) -> str:
            ack, event = await _execute_tool(name, kwargs, read_tool_executor=read_tool_executor,
                                             capability_tool_executor=capability_tool_executor,
                                             seen=seen, trace=trace, publish=publish,
                                             manuscript_ack=manuscript_ack)
            if event is not None:
                await publish(event)
            return ack

        return _run

    tools = [
        StructuredTool.from_function(
            coroutine=make_runner(spec['function']['name']),
            name=spec['function']['name'],
            description=spec['function'].get('description', ''),
            args_schema=_params_model(spec['function']['name'],
                                      spec['function'].get('parameters') or {}))
        for spec in READ_TOOL_SPECS + PROPOSE_TOOLS + CAPABILITY_TOOL_SPECS
    ]
    return _LangGraphToolNode(tools, handle_tool_errors=True)


# 稿件工具的参数即正文本体,只有它从工具参数流里开洞推给作者。
_MANUSCRIPT_TOOL_NAME = 'write_manuscript'
_CONTENT_KEY_RE = re.compile(r'"content"\s*:\s*"')


class _ManuscriptArgsStreamer:
    """从流式 tool_call_chunks 中提取 write_manuscript 的 content 明文增量。

    参数按 OpenAI 增量到达(args 是 JSON 文本片段)。每帧对已累积的
    content 值做前缀式解码:尾部落在转义序列中间时回退到最近的可解码
    边界,与已推前缀的差值即本次增量。全文量级(数千字)下每帧重解码
    的成本可忽略(json 为 C 实现),换来无跨界状态的正确性。
    """

    def __init__(self):
        self._args: dict[int, str] = {}
        self._names: dict[int, str] = {}
        self._content_at: dict[int, int] = {}
        self._pushed: dict[int, int] = {}

    def feed(self, chunk) -> str:
        pieces = []
        for call in getattr(chunk, 'tool_call_chunks', None) or []:
            index = call.get('index') or 0
            name = call.get('name') or self._names.get(index)
            if name is None:
                continue
            self._names[index] = name
            if name != _MANUSCRIPT_TOOL_NAME:
                continue
            self._args[index] = self._args.get(index, '') + (call.get('args') or '')
            piece = self._drain(index)
            if piece:
                pieces.append(piece)
        return ''.join(pieces)

    def _drain(self, index: int) -> str:
        raw = self._args[index]
        start = self._content_at.get(index)
        if start is None:
            match = _CONTENT_KEY_RE.search(raw)
            if match is None:
                return ''
            start = self._content_at[index] = match.end()
        decoded = _decode_json_string_prefix(raw[start:])
        if not decoded:
            return ''
        piece = decoded[self._pushed.get(index, 0):]
        self._pushed[index] = len(decoded)
        return piece


def _decode_json_string_prefix(value: str):
    """解码 JSON 字符串值的安全前缀;尾部落在转义序列中间时回退。"""
    for cut in range(len(value), -1, -1):
        candidate = value[:cut]
        if candidate.endswith('\\'):
            continue
        try:
            return json.loads('"' + candidate + '"')
        except ValueError:
            continue
    return None


def _build_graph(llm, *, read_tool_executor, capability_tool_executor, seen: set[str], trace: AgentTrace, publish,
                 manuscript_ack=None):
    """装配 LangGraph：agent 流式调用模型，tools 执行工具，条件边决定是否继续。"""
    bound = llm.bind_tools(AGENT_TOOLS)

    async def agent(state: _AgentState) -> dict:
        accumulated = None
        # 每轮新建:同一轮对话内模型可能再次起草,状态不跨轮续接。
        manuscript_args = _ManuscriptArgsStreamer()
        async for chunk in stream_model(bound, list(state['messages'])):
            accumulated = chunk if accumulated is None else accumulated + chunk
            text = chunk.text()
            # 带工具请求的一轮文字是过程说明，不作为可使用正文推给作者；
            # 最终答复边生成边推送，保持原有观感。
            if text and not getattr(chunk, 'tool_call_chunks', None):
                await publish({'type': 'chunk', 'content': text})
            # 稿件工具的参数就是正文本体：content 值的明文增量同样逐字推给
            # 作者，长稿不再等到完成才整段回显；其余工具的参数不推。
            manuscript_delta = manuscript_args.feed(chunk)
            if manuscript_delta:
                await publish({'type': 'chunk', 'content': manuscript_delta})
        if accumulated is None:
            return {'messages': []}
        record_stream_usage(accumulated)
        calls = getattr(accumulated, 'tool_calls', None) or []
        if calls:
            return {'messages': [AIMessage(content=accumulated.content or '', tool_calls=calls)]}
        # 最终答复必须过统一完成契约：截断、过滤、空文本一律失败，
        # 不能因为走了流式就放宽原来对完整性的要求。
        parse_model_result(accumulated, max_output_chars=MAX_CHAT_OUTPUT_CHARS)
        return {'messages': [accumulated]}

    def should_continue(state: _AgentState) -> str:
        last = state['messages'][-1]
        if isinstance(last, AIMessage) and getattr(last, 'tool_calls', None):
            return 'tools'
        return END

    workflow = StateGraph(_AgentState)
    workflow.add_node('agent', agent)
    workflow.add_node('tools', _recording_tools(
        read_tool_executor=read_tool_executor, capability_tool_executor=capability_tool_executor,
        seen=seen, trace=trace, publish=publish, manuscript_ack=manuscript_ack))
    workflow.set_entry_point('agent')
    workflow.add_conditional_edges('agent', should_continue, {'tools': 'tools', END: END})
    workflow.add_edge('tools', 'agent')
    return workflow.compile()


async def _forward_events(graph, payload, config, emit) -> None:
    """在同一任务里执行图，事件即时交给调用方；轮次耗尽按已有结果收尾。"""
    try:
        async for _step in graph.astream(payload, config):
            pass
    except GraphRecursionError:
        # 与手写循环到顶同义：保留已产生的提案与稿件，不当作失败。
        logger.warning('Agent 工具调用轮次达到上限，按已有结果收尾')
    finally:
        await emit(None)


async def run_agent(llm, messages: list, *, read_tool_executor=None,
                    capability_tool_executor=None, manuscript_ack=None,
                    max_rounds: int = 8) -> AsyncIterator[dict]:
    """跑一轮 Agent：模型可以多次调用工具，最后给出自然语言回复。

    ``read_tool_executor`` 是 ``(name, args) -> awaitable[str]`` 的受权只读
    检索入口；为 None 时只读工具不可用，模型会收到明确说明而不是静默失败。
    产出事件：``tool``、``chunk``、``final``。
    """
    seen: set[str] = set()
    trace = AgentTrace()
    queue: asyncio.Queue = asyncio.Queue()

    async def publish(event) -> None:
        await queue.put(event)

    graph = _build_graph(llm, read_tool_executor=read_tool_executor,
                         capability_tool_executor=capability_tool_executor, seen=seen,
                         trace=trace, publish=publish, manuscript_ack=manuscript_ack)
    # 一轮 = 一次 agent 步再加一次 tools 步；预算用尽由转发任务收尾。
    # 模型一直请求工具时，图在第 max_rounds 次模型调用后越界并收尾。
    config = {'recursion_limit': max(1, max_rounds) * 2}
    runner = asyncio.create_task(_forward_events(
        graph, {'messages': convert_to_messages(list(messages))}, config, publish))
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
    finally:
        if not runner.done():
            runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner

    # 不确定点只随稿件上报：纯讨论轮次没有可采纳载体，不伪造不确定点。
    final: dict = {'actions': trace.actions,
                   'uncertainties': (trace.manuscript or {}).get('uncertainties', [])}
    operation = None
    decided = 'discuss'
    if trace.manuscript is not None:
        operation = _OPERATION[trace.manuscript['operation']]
        decided = _MODE[trace.manuscript['operation']]
        final['manuscript'] = trace.manuscript
    final['decided_mode'] = decided
    yield {'type': 'final', 'data': final, 'operation': operation,
           'text': (trace.manuscript or {}).get('content')}
