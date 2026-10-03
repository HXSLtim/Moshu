"""Core Agent 事件序契约测试：新核心全场景事件过形状守护。

「前端零改动」验收线(设计稿 §3.6)的测试期锁定——loop 各分支产出的每一
个事件都必须通过 events.assert_nai_event；消费侧字段依赖(chunk.content/
tool.name·status·data/final.data·text·operation)与 writing_chat 消费逻辑
逐字段对照。
"""
from app.services.conversation.core.events import assert_nai_event, validate_nai_event
from app.services.conversation.core.loop import run_core_agent
from app.services.conversation.core.types import ModelResponse
from tests.test_core_agent_loop import SPEC, ScriptedProvider, _call, _resp


async def _events(provider, **kwargs):
    collected = []
    async for event in run_core_agent(provider, [{'role': 'user', 'content': '写'}],
                                      tools_spec=SPEC, **kwargs):
        collected.append(assert_nai_event(event))
    return collected


async def test_all_event_shapes_pass_guard_plain_round():
    provider = ScriptedProvider([_resp(text='你好')])
    events = await _events(provider)
    assert events[-1]['type'] == 'final'
    assert events[-1]['data']['decided_mode'] == 'discuss'


async def test_all_event_shapes_pass_guard_tool_round():
    async def read_executor(name, args):
        return '章节正文' * 40

    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 3})]),
        _resp(stop_reason='toolUse', tool_calls=[_call('propose_fact',
                 {'subject': '李明', 'attribute': '身份', 'value': '剑士'})]),
        _resp(text='整理好了。'),
    ])
    events = await _events(provider, read_tool_executor=read_executor)
    statuses = [e['status'] for e in events if e['type'] == 'tool']
    assert statuses == ['read', 'proposed']


async def test_all_event_shapes_pass_guard_manuscript_round():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('write_manuscript',
                 {'operation': 'append', 'content': '夜色沉了下来。'})]),
        _resp(text='收到。'),
    ])
    events = await _events(provider)
    final = events[-1]
    assert final['type'] == 'final'
    # 消费侧依赖：稿件轮 text/operation 与 manuscript 载荷一致。
    assert final['operation'] == 'append'
    assert final['text'] == '夜色沉了下来。'
    assert final['data']['manuscript']['operation'] == 'append'


async def test_error_final_shape_guarded():
    provider = ScriptedProvider([_resp(stop_reason='error', error='上游故障')])
    events = await _events(provider)
    final = events[-1]
    assert final['data']['stop_reason'] == 'error'
    assert final['data']['error_message'] == '上游故障'


async def test_shape_guard_catches_drift():
    assert validate_nai_event({'type': 'chunk', 'content': 123})
    assert validate_nai_event({'type': 'tool', 'name': 'x', 'status': 'oops', 'data': {}})
    assert validate_nai_event({'type': 'final', 'data': {'decided_mode': 'discuss'}})
    assert validate_nai_event({'type': 'surprise'})
    assert not validate_nai_event({'type': 'chunk', 'content': 'ok'})
