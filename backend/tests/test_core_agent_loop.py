"""Core Agent 循环契约测试：stopReason 分类学、length 拒执行、terminate
拉闸、挂点拦截、取消结构化收尾与 Nai 事件序(chunk/tool/final)。

假 provider 按脚本回事件，覆盖设计稿 §3.1 熔断三件替代物的全部分支。
"""
from types import SimpleNamespace

import pytest

from app.services.conversation.core.loop import run_core_agent
from app.services.conversation.core.types import ModelResponse

SPEC = [{'type': 'function', 'function': {'name': 'read_chapter',
         'description': '读章', 'parameters': {'type': 'object', 'properties': {}}}},
        {'type': 'function', 'function': {'name': 'propose_fact',
         'description': '提案', 'parameters': {'type': 'object', 'properties': {}}}},

        {'type': 'function', 'function': {'name': 'write_manuscript',
         'description': '稿件', 'parameters': {'type': 'object', 'properties': {}}}}]


class ScriptedProvider:
    """按脚本依次回放每轮模型响应；记录每轮收到的消息。"""

    def __init__(self, responses: list[ModelResponse]):
        self.responses = list(responses)
        self.requests: list[list[dict]] = []

    async def stream(self, messages, tools=None):
        self.requests.append([dict(m) for m in messages])
        response = self.responses.pop(0)
        if response.text:
            yield {'type': 'text_delta', 'delta': response.text}
        for i, call in enumerate(response.tool_calls):
            yield {'type': 'toolcall_start', 'index': i, 'id': call['id'], 'name': call['name']}
            import json as _json
            yield {'type': 'toolcall_delta', 'index': i,
                   'args_delta': _json.dumps(call['arguments'], ensure_ascii=False)}
        yield {'type': 'response_done', 'response': response}


def _call(name, arguments=None, cid='c1'):
    return {'id': cid, 'name': name, 'arguments': arguments or {}}


def _resp(stop_reason='stop', text='', tool_calls=None, usage=None, error=None):
    return ModelResponse(stop_reason=stop_reason, text=text,
                         tool_calls=tool_calls or [], usage=usage, error_message=error)


async def _run(provider, **kwargs):
    events = []
    async for event in run_core_agent(provider, [{'role': 'user', 'content': '写'}],
                                      tools_spec=SPEC, **kwargs):
        events.append(event)
    return events


def _final(events):
    assert events[-1]['type'] == 'final'
    return events[-1]


# ---------- 基础轮次 ----------

async def test_plain_text_round_streams_chunks_and_final():
    provider = ScriptedProvider([_resp(text='你好')])
    events = await _run(provider)
    kinds = [e['type'] for e in events]
    assert kinds == ['chunk', 'final']
    assert events[0] == {'type': 'chunk', 'content': '你好'}
    final = events[1]
    assert final['data']['decided_mode'] == 'discuss'
    assert final['text'] is None  # 旧链语义：text 仅稿件轮有值，纯文本轮回复在 chunk 流
    assert final['operation'] is None


async def test_read_tool_round_then_final_reply():
    async def read_executor(name, args):
        assert name == 'read_chapter'
        return '第三章正文……' * 30

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 3})]),
        _resp(text='这是第三章的内容。'),
    ])
    events = await _run(provider, read_tool_executor=read_executor)
    kinds = [e['type'] for e in events]
    assert kinds == ['tool', 'chunk', 'final']
    tool_event = events[0]
    assert tool_event['name'] == 'read_chapter' and tool_event['status'] == 'read'
    # 前端预览按既有预算截断，与旧链 compact_text(120) 同口径。
    assert len(tool_event['data']['summary']) <= 120
    # 第二轮模型消息含工具结果回填。
    tool_result_messages = [m for m in provider.requests[1] if m.get('role') == 'tool']
    assert tool_result_messages and '第三章正文' in tool_result_messages[0]['content']


async def test_tool_unavailable_when_no_executor():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter')]),
        _resp(text='好，直接回答。'),
    ])
    events = await _run(provider)  # 未提供 read_tool_executor
    # 旧链语义：不可用工具不发前端事件，只把明确说明回填给模型。
    assert [e['type'] for e in events] == ['chunk', 'final']
    tool_result = [m for m in provider.requests[1] if m.get('role') == 'tool'][0]
    assert '没有检索工具可用' in tool_result['content']


async def test_duplicate_tool_signature_acked_once():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 3}),
                                                 _call('read_chapter', {'chapter': 3}, cid='c2')]),
        _resp(text='答'),
    ])
    calls = []

    async def read_executor(name, args):
        calls.append(args)
        return 'ok'

    events = await _run(provider, read_tool_executor=read_executor)
    assert len(calls) == 1  # 同签名第二次不执行
    tool_results = [m for m in provider.requests[1] if m.get('role') == 'tool']
    assert '重复调用已忽略' in tool_results[1]['content']


# ---------- 熔断三件替代物 ----------

async def test_length_stop_rejects_all_tool_calls():
    """length(截断)→该消息全部工具调用拒绝执行，错误结果回模型重发。"""
    provider = ScriptedProvider([
        _resp(stop_reason='length', tool_calls=[_call('read_chapter', {'chapter': 3})]),
        _resp(text='重新组织后的回答'),
    ])
    events = await _run(provider, read_tool_executor=lambda n, a: 'should-not-run')
    tool_events = [e for e in events if e['type'] == 'tool']
    assert tool_events and '未执行' in tool_events[0]['data']['summary']
    tool_result = [m for m in provider.requests[1] if m.get('role') == 'tool'][0]
    assert '未执行' in tool_result['content']


async def test_error_response_hard_exit_with_partial_final():
    """error 硬分支：保留已产生的提案/稿件，不重试不吞，final 带错误态。"""
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('propose_fact',
                 {'subject': '李明', 'attribute': '身份', 'value': '剑士'}, cid='c1')]),
        _resp(stop_reason='error', error='上游 500'),
    ])
    events = await _run(provider)
    final = _final(events)
    assert final['data']['stop_reason'] == 'error'
    assert final['data']['error_message'] == '上游 500'
    # 已登记的提案保留在收尾里，不因后续失败丢弃。
    assert final['data']['actions'][0]['subject'] == '李明'


async def test_aborted_response_structured_final():
    provider = ScriptedProvider([_resp(stop_reason='aborted', text='写到一半', error='已取消')])
    events = await _run(provider)
    final = _final(events)
    assert final['data']['stop_reason'] == 'aborted'
    assert final['data']['error_message'] == '已取消'


async def test_terminate_flag_stops_loop_after_batch():
    """工具结果 terminate 拉闸：整批全 terminate 才停，不再回模型。"""
    async def read_executor(name, args):
        return 'done'

    def after_tool_call(name, args, result):
        result.terminate = True
        return result

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 1})]),
    ])
    events = await _run(provider, read_tool_executor=read_executor,
                        after_tool_call=after_tool_call)
    assert len(provider.requests) == 1  # 没有第二次模型调用
    final = _final(events)
    assert final['data']['decided_mode'] == 'discuss'


async def test_single_terminate_among_batch_does_not_stop():
    """批内只有一个 terminate 不拉闸：必须整批全 terminate。"""
    async def read_executor(name, args):
        return 'ok'

    def after_tool_call(name, args, result):
        if args.get('chapter') == 1:
            result.terminate = True
        return result

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 1}),
                                                 _call('read_chapter', {'chapter': 2}, cid='c2')]),
        _resp(text='继续回答'),
    ])
    events = await _run(provider, read_tool_executor=read_executor,
                        after_tool_call=after_tool_call)
    assert len(provider.requests) == 2


async def test_before_tool_call_block_returns_error_result():
    def before_tool_call(name, args):
        return {'block': True, 'reason': '越界访问被拒绝'}

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 999})]),
        _resp(text='抱歉，该章不可读。'),
    ])
    events = await _run(provider, read_tool_executor=lambda n, a: 'leaked!',
                        before_tool_call=before_tool_call)
    tool_result = [m for m in provider.requests[1] if m.get('role') == 'tool'][0]
    assert '越界访问被拒绝' in tool_result['content']


# ---------- 提案与稿件 ----------

async def test_propose_fact_registered_and_evented():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('propose_fact',
                 {'subject': '李明', 'attribute': '身份', 'value': '剑士'})]),
        _resp(text='已记下设定。'),
    ])
    events = await _run(provider)
    proposed = [e for e in events if e['type'] == 'tool' and e['status'] == 'proposed']
    assert proposed and proposed[0]['data']['subject'] == '李明'
    final = _final(events)
    assert final['data']['actions'][0]['kind'] == 'fact'


async def test_manuscript_streamed_and_final_payload():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('write_manuscript',
                 {'operation': 'append', 'content': '夜色沉了下来。', 'title': None})]),
        _resp(text='稿件已收到。'),
    ])
    events = await _run(provider)
    kinds = [e['type'] for e in events]
    # 稿件 content 明文增量逐字推 + drafted 工具事件 + 次轮确认文本 + final。
    assert kinds == ['chunk', 'tool', 'chunk', 'final']
    assert events[0]['content'] == '夜色沉了下来。'
    drafted = events[1]
    assert drafted['status'] == 'drafted' and drafted['name'] == 'write_manuscript'
    final = _final(events)
    assert final['data']['decided_mode'] == 'continue'
    assert final['operation'] == 'append'
    assert final['data']['manuscript']['content'] == '夜色沉了下来。'


async def test_manuscript_ack_uses_generator():
    def manuscript_ack(draft):
        return f'已收到正文稿件，将落在第 {draft.get("landing_chapter", 7)} 章。'

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('write_manuscript',
                 {'operation': 'append', 'content': '正文。'})]),
        _resp(text='好。'),
    ])
    events = await _run(provider, manuscript_ack=manuscript_ack)
    # 回执回填给模型，次轮请求里可查。
    tool_result = [m for m in provider.requests[1] if m.get('role') == 'tool'][0]
    assert '第 7 章' in tool_result['content']
    final = _final(events)
    assert final['data']['manuscript']['content'] == '正文。'


# ---------- 预算与轮次 ----------

async def test_model_call_budget_exhausted_raises():
    from app.services.model.execution import ExecutionBudgetError
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': i})])
        for i in range(3)
    ])

    async def read_executor(name, args):
        return 'ok'

    with pytest.raises(ExecutionBudgetError):
        await _run(provider, read_tool_executor=read_executor, max_model_calls=2)


# ---------- steering ----------

async def test_steering_message_injected_between_rounds():
    pending = [{'role': 'user', 'content': '顺便检查伏笔'}]

    def get_pending_messages():
        drained = pending[:]
        pending.clear()
        return drained

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 1})]),
        _resp(text='处理完了。'),
    ])

    async def read_executor(name, args):
        return 'ok'

    events = await _run(provider, read_tool_executor=read_executor,
                        get_pending_messages=get_pending_messages)
    second_round = provider.requests[1]
    steering = [m for m in second_round if m.get('content') == '顺便检查伏笔']
    assert steering and steering[0]['role'] == 'user'
