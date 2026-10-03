"""Core Agent 循环：双层循环 + stopReason 分类学 + 熔断三件替代物。

参考 pi Core(packages/agent/src/agent-loop.ts runLoop)移植，语义按 Nai 域
收敛(设计稿 §3.1)：不设 maxTurns，熔断=①stopReason 硬分支(error/aborted
保留已产生结果直接收尾；length 拒执行整批工具调用、错误结果回模型重发)
②工具结果 terminate 拉闸(整批全 terminate 才停批)③重试预算独立于循环
(域策略 max_model_calls，耗尽抛 ExecutionBudgetError 与旧链同语义)。
事件出口=旧链 Nai 形状(tool/chunk/final)——「前端零改动」验收线。
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from loguru import logger

from app.services.context.budget import MAX_CHAT_OUTPUT_CHARS, MAX_TRACE_PREVIEW_CHARS, compact_text
from app.services.context.builder import ContextScopeError
from app.services.conversation.capability_tools import CAPABILITY_TOOL_NAMES
from app.services.conversation.tools import CHECK_TOOL_NAME, READ_TOOL_NAMES
from app.services.model.result import ModelOutputError
from app.services.conversation.core.assembly import ManuscriptStream
from app.services.conversation.core.budget import BudgetExceeded, CoreBudget
from app.services.conversation.core.compaction import (
    CompactionSettings,
    build_post_compaction_messages,
    compact,
    estimate_context_tokens,
    prepare_compaction,
    should_compact,
)
from app.services.conversation.core.models import get_model
from app.services.conversation.core.tools import (
    DUPLICATE_CALL_ACK,
    MODE,
    OPERATION,
    TOOLS_UNAVAILABLE_ACK,
    execute_agent_tool,
)
from app.services.conversation.core.types import ModelResponse, ToolResult

_LENGTH_REJECT_ACK = '工具调用 {name} 未执行：本次回复命中输出上限，参数可能不完整，请重新发起完整的调用。'
_LENGTH_REJECT_SUMMARY = '未执行：输出截断，参数可能不完整，等待重发。'
_READ_FAILURE_ACK = '检索工具暂时不可用，请基于已有上下文回答，并说明该信息未能核实。'
_CAPABILITY_FAILURE_ACK = '工具 {name} 执行失败,请向作者说明。'


def _assistant_message(response: ModelResponse) -> dict:
    """OpenAI dict 形状的 assistant 消息；带工具调用时 arguments 序列化为字符串。"""
    message: dict = {'role': 'assistant', 'content': response.text or ''}
    if response.tool_calls:
        message['tool_calls'] = [
            {'id': call['id'], 'type': 'function',
             'function': {'name': call['name'],
                          'arguments': json.dumps(call['arguments'], ensure_ascii=False)}}
            for call in response.tool_calls]
    return message


def _tool_message(tool_call_id: str, content: str) -> dict:
    return {'role': 'tool', 'tool_call_id': tool_call_id, 'content': content}


def _final_event(actions: list[dict], manuscript: dict | None,
                 stop_reason: str, error_message: str | None, rounds: int) -> dict:
    data: dict = {'actions': actions,
                  'uncertainties': (manuscript or {}).get('uncertainties', []),
                  'decided_mode': MODE[manuscript['operation']] if manuscript else 'discuss',
                  'stop_reason': stop_reason, 'error_message': error_message, 'rounds_used': rounds}
    operation = None
    text = None
    if manuscript is not None:
        data['manuscript'] = manuscript
        operation = OPERATION[manuscript['operation']]
        text = manuscript.get('content')
    return {'type': 'final', 'data': data, 'operation': operation, 'text': text}


async def run_core_agent(provider, messages: list[dict], *, tools_spec: list[dict],
                         read_tool_executor=None, capability_tool_executor=None,
                         manuscript_ack=None, before_tool_call=None, after_tool_call=None,
                         max_model_calls: int = 20, budget: CoreBudget | None = None,
                         max_rounds: int = 8, compaction: CompactionSettings | None = None,
                         summarize=None, get_pending_messages=None) -> AsyncIterator[dict]:
    """跑一轮 Agent：模型可多次调用工具，最后给出自然语言回复。

    产出旧链 Nai 形状事件：``tool``、``chunk``、``final``。工具执行器签名
    与挂点形状见 types.py；预算三口径(次数/token/钱)由域策略经 budget 注入，
    传 max_model_calls 时按单口径构造(向后兼容)。
    """
    if budget is None:
        budget = CoreBudget(max_model_calls=max_model_calls)
    conversation: list[dict] = [dict(m) for m in messages]
    seen: set[str] = set()
    actions: list[dict] = []
    manuscript: dict | None = None
    calls_used = 0
    rounds = 0

    while True:
        if rounds >= max_rounds:
            # 轮次软闸(对齐旧链 recursion 语义)：到顶按已有结果收尾不判失败，
            # 已登记的提案与稿件不丢；预算硬闸(budget)另行拦截。
            yield _final_event(actions, manuscript, 'stop', None, rounds)
            return
        rounds += 1
        # 每轮新建：同一轮对话内模型可能再次起草，稿件流状态不跨轮续接。
        assembler = ManuscriptStream()
        response: ModelResponse | None = None
        async for event in provider.stream(list(conversation), tools=tools_spec):
            kind = event['type']
            if kind == 'text_delta':
                yield {'type': 'chunk', 'content': event['delta']}
            elif kind in ('toolcall_start', 'toolcall_delta'):
                # 稿件工具的参数即正文本体：content 明文增量同样逐字推给作者。
                piece = assembler.feed(event)
                if piece:
                    yield {'type': 'chunk', 'content': piece}
            elif kind == 'response_done':
                response = event['response']
        calls_used += 1
        if response is None:
            raise ModelOutputError('empty_reply', '模型没有返回可显示的回复，请重新发送。')
        # 预算三口径记账与检查：token/钱按 provider 实报 usage 累计，
        # usage 缺席(不伪造)时对应口径休眠；超限在此拦下不发起下一轮。
        budget.record_call(response.usage)
        budget.check(total_calls=calls_used)

        # error/aborted 硬分支：保留已产生的提案与稿件，不重试不吞，直接收尾。
        if response.stop_reason in ('error', 'aborted'):
            yield _final_event(actions, manuscript, response.stop_reason,
                               response.error_message, rounds)
            return

        if response.tool_calls:
            conversation.append(_assistant_message(response))
            # length(截断)：截断的参数「能解析但可能不完整」，整批拒绝执行，
            # 错误结果回填让模型重发——不执行可能被腰斩的调用。
            if response.stop_reason == 'length':
                for call in response.tool_calls:
                    ack = _LENGTH_REJECT_ACK.format(name=call['name'])
                    conversation.append(_tool_message(call['id'], ack))
                    yield {'type': 'tool', 'name': call['name'], 'status': 'completed',
                           'data': {'summary': _LENGTH_REJECT_SUMMARY}}
                continue

            batch_terminate = True
            for call in response.tool_calls:
                name = call['name'] or ''
                args = call['arguments'] or {}
                signature = f'{name}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}'
                if signature in seen:
                    conversation.append(_tool_message(call['id'], DUPLICATE_CALL_ACK))
                    continue
                seen.add(signature)

                result, tool_events = await _run_tool(
                    name, args, read_tool_executor=read_tool_executor,
                    capability_tool_executor=capability_tool_executor,
                    before_tool_call=before_tool_call, after_tool_call=after_tool_call,
                    actions=actions)
                if isinstance(result, ManuscriptOutcome):
                    # 稿件登记后由回执生成器给出真实落点(章号)说明，
                    # 缺失或失败时退回不含章号的通用回执。
                    draft = result.draft
                    ack = result.content
                    if manuscript_ack is not None:
                        try:
                            ack = manuscript_ack(draft)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning('稿件回执生成失败,退回通用回执: {}', exc)
                    result = ToolResult(content=ack, terminate=result.terminate)
                    manuscript = draft
                batch_terminate = batch_terminate and bool(result.terminate)
                conversation.append(_tool_message(call['id'], result.content))
                for tool_event in tool_events:
                    yield tool_event
            if batch_terminate:
                # terminate 拉闸：整批全部拉闸才停，收尾保留已登记结果。
                yield _final_event(actions, manuscript, 'stop', None, rounds)
                return
            # 轮间压缩(prepareNextTurn 语义，设计稿 §3.1「压缩从此挂入」)：
            # 工具批完成后、下一模型调用前，超限即压缩重建会话；摘要失败
            # 拒落盘纪律由 compact 透传异常——轮次明确失败而非静默降级。
            if compaction is not None:
                estimate = estimate_context_tokens(conversation)
                window = get_model(getattr(provider, 'model', None)).context_window
                if should_compact(estimate['tokens'], window, compaction):
                    preparation = prepare_compaction(conversation, compaction)
                    if preparation is not None:
                        if summarize is None:
                            from app.services.conversation.core.compaction import make_provider_summarizer
                            summarize = make_provider_summarizer(provider)
                        result = await compact(preparation, summarize)
                        conversation = build_post_compaction_messages(conversation, result)
            # steering：工具批完成后注入排队消息，与前端排队输入语义对齐。
            if get_pending_messages is not None:
                for pending in get_pending_messages() or []:
                    conversation.append(dict(pending))
            continue

        # 最终答复：完成契约与旧链一致——截断、空文本、超限一律失败，不因新核心放宽。
        if response.stop_reason == 'length':
            raise ModelOutputError('output_truncated', '模型回复被截断，内容不完整，请重新发送。')
        text = (response.text or '').strip()
        if not text:
            raise ModelOutputError('empty_reply', '模型没有返回可显示的回复，请重新发送。')
        if len(text) > MAX_CHAT_OUTPUT_CHARS:
            raise ModelOutputError('output_truncated', '模型回复超出可用长度，请缩小任务后重新发送。')
        yield _final_event(actions, manuscript, 'stop', None, rounds)
        return


class ManuscriptOutcome(ToolResult):
    """稿件登记的载体：draft 交由 loop 层挂 manuscript_ack 生成回执。"""

    def __init__(self, draft: dict, ack: str):
        super().__init__(content=ack)
        self.draft = draft


async def _run_tool(name: str, args: dict, *, read_tool_executor, capability_tool_executor,
                    before_tool_call, after_tool_call,
                    actions: list[dict]) -> tuple[ToolResult, list[dict]]:
    """执行一次工具调用并组装三通道结果与前端事件列表。

    作者身份/生命周期/越界类作用域错误(ContextScopeError)必须向上抛出，
    不能降级为无界检索——与旧链异常纪律一致。
    """
    if before_tool_call is not None:
        try:
            decision = before_tool_call(name, args) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning('before_tool_call 挂点失败({})：{}', name, exc)
            decision = {}
        if decision.get('block'):
            reason = str(decision.get('reason') or 'Tool execution was blocked')
            return (ToolResult(content=reason, is_error=True, terminate=bool(decision.get('terminate'))),
                    [{'type': 'tool', 'name': name, 'status': 'completed',
                      'data': {'summary': compact_text(reason, 120, keep='head')}}])

    result, events = await _dispatch_tool(name, args, read_tool_executor=read_tool_executor,
                                          capability_tool_executor=capability_tool_executor,
                                          actions=actions)
    if after_tool_call is not None:
        try:
            overridden = after_tool_call(name, args, result)
            if overridden is not None:
                result = overridden
        except Exception as exc:  # noqa: BLE001
            logger.warning('after_tool_call 挂点失败({})：{}', name, exc)
            result = ToolResult(content=_CAPABILITY_FAILURE_ACK.format(name=name), is_error=True)
    return result, events


async def _dispatch_tool(name: str, args: dict, *, read_tool_executor,
                         capability_tool_executor, actions: list[dict]) -> tuple[ToolResult, list[dict]]:
    """按工具族分发：只读检索/能力工具经执行器，提案与稿件只登记。"""
    if name in READ_TOOL_NAMES:
        if read_tool_executor is None:
            return ToolResult(content=TOOLS_UNAVAILABLE_ACK), []
        try:
            value = await read_tool_executor(name, args)
        except ContextScopeError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning('Agent 只读工具 {} 执行失败：{}', name, exc)
            value = _READ_FAILURE_ACK
        status = 'checked' if name == CHECK_TOOL_NAME else 'read'
        return (ToolResult(content=value),
                [{'type': 'tool', 'name': name, 'status': status,
                  'data': {'summary': compact_text(value, MAX_TRACE_PREVIEW_CHARS, keep='head')}}])
    if name in CAPABILITY_TOOL_NAMES:
        if capability_tool_executor is None:
            return ToolResult(content=TOOLS_UNAVAILABLE_ACK), []
        # 能力工具先发 running 事件，长任务(编排/续写)期间前端有可感知进度。
        running = {'type': 'tool', 'name': name, 'status': 'running',
                   'data': {'summary': compact_text(args.get('instruction') or args.get('query') or '',
                                                    60, keep='head')}}
        try:
            value = await capability_tool_executor(name, args)
        except ContextScopeError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning('Agent 能力工具 {} 执行失败：{}', name, exc)
            value = _CAPABILITY_FAILURE_ACK.format(name=name)
        return (ToolResult(content=value),
                [running, {'type': 'tool', 'name': name, 'status': 'completed',
                           'data': {'summary': compact_text(value, MAX_TRACE_PREVIEW_CHARS, keep='head')}}])

    action, draft, ack = execute_agent_tool(name, args)
    if action is not None:
        actions.append(action)
        return (ToolResult(content=ack),
                [{'type': 'tool', 'name': name, 'status': 'proposed', 'data': action}])
    if draft is not None:
        return ManuscriptOutcome(draft, ack), [{'type': 'tool', 'name': name, 'status': 'drafted', 'data': draft}]
    return ToolResult(content=ack), []
