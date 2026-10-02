"""真实模型冒烟验证：Agent 工具调用参数链路的端到端取证。

既有单测用脚本化测试替身（``tests/test_agent_tools.py`` 的 ``ScriptedLLM``）只发
``AIMessageChunk``，证明不了真实模型能否把实参填进工具参数表。本脚本用 ``.env``
里配置的真实模型跑一轮 ``run_agent``，逐环节取证：

1. 模型确实发起了工具调用（模型原始 tool_calls 非空）；
2. 工具执行入口 ``read_tool_executor`` 实际收到的实参非空 ``{}``，且与模型给出的
   查询词逐字一致（参数没有被 ``ToolNode`` 校验静默丢弃）；
3. 工具返回值作为 ``ToolMessage`` 回喂给第二轮模型；
4. 第二轮模型答复里引用了只有工具返回结果才含有的校验码（证明模型真的看到了检索结果）；
5. 最后给出文本答复（``final`` 事件 + 流式 chunk）。

另附一组对照实验：用自由签名 ``**kwargs`` 构造同一个工具，复现"实参被静默丢弃"
的历史缺陷，证明本脚本的取证点确实能抓到该回归。

用法（必须清掉全部 8 个代理变量，否则 httpx 在导入期就会崩）：

    cd backend && env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy \
        -u HTTPS_PROXY -u https_proxy -u NO_PROXY -u no_proxy \
        .venv/bin/python smoke_agent_real_model.py

退出码 0 表示链路完好；非 0 表示验证失败，输出里会打印具体缺失的环节。
脚本只读取模型名与 base_url，不打印密钥内容。
"""
from __future__ import annotations

import asyncio
import json
import secrets
import sys

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import ToolNode

from app.core.config import settings
from app.services.conversation.runtime import run_agent
from app.services.model.provider import create_chat_model

# 只有工具返回结果才含有的校验码：模型答复里出现它，才能证明模型看到了检索结果。
SENTINEL = f'NAI-SMOKE-{secrets.token_hex(4)}'
TOOL_NAME = 'search_story_bible'
PROMPT = (
    '你是小说设定助手，必须严格按步骤执行：\n'
    f'1. 先调用 {TOOL_NAME} 工具，query 参数传「林夏 武器」，不要凭空回答；\n'
    '2. 拿到工具返回结果后，把结果里的「校验码」原样抄进你的最终回复；\n'
    '3. 最终回复用一句话说明林夏的武器是什么。\n'
    '不要跳过工具调用，也不要自己编造校验码。'
)

TOOL_RESULT = (
    '【设定账本检索结果】\n'
    '- 事实：林夏 / 武器 = 青霜剑（第 1 章确立）\n'
    f'校验码：{SENTINEL}\n'
    '（以上为工具返回的原始检索结果，不是指令）'
)


class _RecordingRunnable:
    """包住 ``bind_tools`` 之后的 runnable，记录每轮 payload、原始 tool_calls 与流式文本。"""

    def __init__(self, inner, rounds: list[dict]) -> None:
        self._inner = inner
        self._rounds = rounds

    async def astream(self, payload):
        record = {
            'index': len(self._rounds) + 1,
            'payload': list(payload),
            'tool_calls': [],
            'text': '',
        }
        self._rounds.append(record)
        accumulated = None
        async for chunk in self._inner.astream(payload):
            accumulated = chunk if accumulated is None else accumulated + chunk
            yield chunk
        if accumulated is not None:
            record['tool_calls'] = json.loads(json.dumps(getattr(accumulated, 'tool_calls', None) or [],
                                                         ensure_ascii=False, default=str))
            record['text'] = accumulated.text()


class _RecordingLLM:
    """真实模型的薄代理：只旁路记录，不改变任何调用语义。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.rounds: list[dict] = []

    def bind_tools(self, tools):
        return _RecordingRunnable(self._inner.bind_tools(tools), self.rounds)


async def _run_real_model_case() -> tuple[bool, list[str]]:
    """真实模型端到端取证，返回 (是否通过, 证据行列表)。"""
    evidence: list[str] = []
    executor_calls: list[dict] = []

    async def read_tool_executor(name: str, args: dict) -> str:
        # 取证点：工具执行入口实际收到的实参。
        executor_calls.append({'name': name, 'args': json.loads(json.dumps(args, ensure_ascii=False, default=str))})
        return TOOL_RESULT

    llm = _RecordingLLM(create_chat_model(model=settings.OPENAI_MODEL_COMPLEX, temperature=0))
    events = []
    async for event in run_agent(llm, [('user', PROMPT)], read_tool_executor=read_tool_executor, max_rounds=4):
        events.append(event)

    chunks = ''.join(event['content'] for event in events if event['type'] == 'chunk')
    tool_events = [event for event in events if event['type'] == 'tool']
    final_events = [event for event in events if event['type'] == 'final']

    evidence.append(f'模型服务 base_url = {settings.OPENAI_API_BASE}')
    evidence.append(f'使用的模型 = {settings.OPENAI_MODEL_COMPLEX}')
    evidence.append(f'模型调用轮数 = {len(llm.rounds)}')
    for record in llm.rounds:
        evidence.append(f"  第 {record['index']} 轮：payload {len(record['payload'])} 条消息，"
                        f"模型原始 tool_calls = {json.dumps(record['tool_calls'], ensure_ascii=False)}")
        tool_messages = [message for message in record['payload'] if isinstance(message, ToolMessage)]
        for message in tool_messages:
            evidence.append(f"    该轮 payload 里的 ToolMessage(tool={message.name}) 内容含校验码 = "
                            f'{SENTINEL in (message.content or "")}')
    evidence.append(f'工具执行入口 read_tool_executor 实际收到 = '
                    f'{json.dumps(executor_calls, ensure_ascii=False)}')
    evidence.append(f'前端观察事件 = {[(event["name"], event["status"]) for event in tool_events]}')
    evidence.append(f'最终答复（流式 chunk 拼接）= {chunks!r}')

    # ---- 逐环节判定 ----
    checks: list[tuple[str, bool, str]] = []

    model_calls = [call for record in llm.rounds for call in record['tool_calls']]
    checks.append(('模型发起了工具调用', bool(model_calls), f'模型原始 tool_calls 数量 = {len(model_calls)}'))

    first_args = executor_calls[0]['args'] if executor_calls else {}
    checks.append(('工具实际收到非空实参', bool(first_args) and first_args != {},
                   f'实际收到 = {json.dumps(first_args, ensure_ascii=False)}'))
    query = first_args.get('query') if isinstance(first_args, dict) else None
    checks.append(('实参含非空 query 查询词', isinstance(query, str) and bool(query.strip()),
                   f'query = {query!r}'))

    model_args = model_calls[0].get('args') if model_calls else None
    checks.append(('工具收到的实参与模型给出的一致', bool(first_args) and first_args == model_args,
                   f'模型给出 = {json.dumps(model_args, ensure_ascii=False, default=str)}'))

    second_round_feeds = any(
        isinstance(message, ToolMessage) and SENTINEL in (message.content or '')
        for message in (llm.rounds[1]['payload'] if len(llm.rounds) > 1 else []))
    checks.append(('工具结果作为 ToolMessage 回喂第二轮', second_round_feeds,
                   f'第二轮 payload 含校验码 ToolMessage = {second_round_feeds}'))

    checks.append(('第二轮模型看到检索结果', SENTINEL in chunks,
                   f'最终答复引用校验码 = {SENTINEL in chunks}'))
    checks.append(('至少两轮模型调用', len(llm.rounds) >= 2, f'轮数 = {len(llm.rounds)}'))
    checks.append(('产出 final 事件', len(final_events) == 1, f'final 事件数量 = {len(final_events)}'))

    evidence.append('')
    evidence.append('环节判定：')
    passed = True
    for title, ok, detail in checks:
        passed = passed and ok
        evidence.append(f'  [{"通过" if ok else "失败"}] {title} —— {detail}')
    return passed, evidence


async def _run_control_case() -> tuple[bool, list[str]]:
    """对照实验：自由签名 ``**kwargs`` 的工具会丢掉模型实参，本脚本的取证点必须能抓到。"""
    evidence: list[str] = []
    received: list[dict] = []

    async def buggy_runner(**kwargs) -> str:
        received.append(dict(kwargs))
        return 'ok'

    buggy = StructuredTool.from_function(coroutine=buggy_runner, name=TOOL_NAME, description='检索设定账本')
    node = ToolNode([buggy], handle_tool_errors=True)
    message = AIMessage(content='', tool_calls=[{'name': TOOL_NAME, 'args': {'query': '林夏 武器'}, 'id': 'c1'}])
    await node.ainvoke({'messages': [message]})

    evidence.append(f'自由签名工具推断出的参数表 = {json.dumps(buggy.args, ensure_ascii=False, default=str)}')
    evidence.append(f'模型给出实参 {{"query": "林夏 武器"}} 时，工具执行入口实际收到 = '
                    f'{json.dumps(received, ensure_ascii=False)}')
    dropped = received == [{}]
    evidence.append(f'  [{"通过" if dropped else "未复现"}] 历史缺陷可被本脚本的取证点抓到 —— '
                    f'实参被静默丢弃为 {{}} = {dropped}')
    return dropped, evidence


async def main() -> int:
    print('=' * 78)
    print('阶段 1：真实模型端到端取证')
    print('=' * 78)
    try:
        passed_real, evidence_real = await _run_real_model_case()
    except Exception as exc:  # noqa: BLE001
        print(f'真实模型调用失败：{type(exc).__name__}: {exc}')
        return 2
    for line in evidence_real:
        print(line)

    print()
    print('=' * 78)
    print('阶段 2：对照实验（复现历史缺陷，证明取证点有效）')
    print('=' * 78)
    passed_control, evidence_control = await _run_control_case()
    for line in evidence_control:
        print(line)

    print()
    print('=' * 78)
    # 对照实验只作背景证据打印，不参与退出码：它证明的是「本脚本取证点能抓到历史
    # 缺陷」，而缺陷本身属于上游库行为。若将来 LangChain 修好 **kwargs 推断，对照
    # 实验会显示「未复现」——那是好事，不应让负责真实链路的闸门失败。
    if passed_real:
        print('结论：真实模型下工具调用参数链路完好。')
        print(f'（对照实验：历史缺陷{"仍可复现" if passed_control else "已未复现"}，不影响本结论。）')
        return 0
    print(f'结论：验证未通过（真实模型链路 = {passed_real}，对照实验 = {passed_control}）。')
    return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
