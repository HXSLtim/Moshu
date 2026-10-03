"""压缩挂点接线测试：轮间压缩编排进 core loop（estimate→should_compact→
compact→重建会话），compaction 模块从零外部调用者变为产品链可达。"""
import pytest

from app.services.conversation.core.compaction import CompactionSettings
from app.services.conversation.core.loop import run_core_agent
from app.services.conversation.core.models import ModelInfo, register_model
from app.services.conversation.core.types import ModelResponse
from tests.core_agent_stub import CoreAgentStub


def _settings(**overrides):
    defaults = dict(enabled=True, reserve_tokens=200, keep_recent_tokens=50)
    defaults.update(overrides)
    return CompactionSettings(**defaults)


def _tool_response(query='查设定'):
    return ModelResponse(stop_reason='toolUse', tool_calls=[
        {'id': 'c1', 'name': 'search_story_bible', 'arguments': {'query': query}}])


async def _run(provider, messages, **kwargs):
    events = []
    async for event in run_core_agent(provider, messages, tools_spec=[], **kwargs):
        events.append(event)
    return events


async def test_round_gap_compaction_rebuilds_conversation():
    """工具批完成后、下一模型调用前：超限即压缩重建，下一轮消息带头检查点。"""
    register_model(ModelInfo(id='tiny-window', name='T', context_window=400,
                             max_tokens=256, cost={}))
    provider = CoreAgentStub([
        _tool_response(),                                   # 轮1 工具调用
        ModelResponse(stop_reason='stop', text='已处理。'),  # 轮2 收尾
    ])
    provider.model = 'tiny-window'

    async def summarize(messages, previous_summary, custom_instructions=None):
        return '压缩摘要：保章号/设定键'

    long_history = [{'role': 'user', 'content': '长问' + '字' * 300},
                    {'role': 'assistant', 'content': '长答' + '字' * 300}]
    events = await _run(provider, long_history,
                        read_tool_executor=lambda name, args: '查到了',
                        compaction=_settings(), summarize=summarize)
    assert events[-1]['type'] == 'final'
    second_round = provider.calls[1]
    # 下一轮消息=检查点带头+保留区；被摘要的旧问不再原样在场。
    assert second_round[0].get('is_compaction') is True
    # 切点落轮中(split-turn)：主区空走「暂无前情」+轮前缀摘要拼接。
    assert '压缩摘要：保章号/设定键' in second_round[0]['summary']
    joined = str(second_round)
    assert '长问' not in joined


async def test_no_compaction_when_under_threshold():
    """未超限零压缩：轮间消息原样，无检查点注入。"""
    register_model(ModelInfo(id='wide-window', name='W', context_window=100000,
                             max_tokens=8192, cost={}))
    provider = CoreAgentStub([
        _tool_response(),
        ModelResponse(stop_reason='stop', text='已处理。'),
    ])
    provider.model = 'wide-window'
    events = await _run(provider, [{'role': 'user', 'content': '短问'}],
                        read_tool_executor=lambda name, args: 'ok',
                        compaction=_settings())
    second_round = provider.calls[1]
    assert all(not m.get('is_compaction') for m in second_round)
    assert any(m.get('content') == '短问' for m in second_round)


async def test_compaction_failure_propagates():
    """摘要失败拒落盘纪律：压缩异常向上传播，轮次明确失败。"""
    register_model(ModelInfo(id='tiny2', name='T2', context_window=400,
                             max_tokens=256, cost={}))
    provider = CoreAgentStub([_tool_response()])
    provider.model = 'tiny2'

    async def summarize(messages, previous_summary, custom_instructions=None):
        raise RuntimeError('Summarization failed: generation hit the token cap')

    with pytest.raises(RuntimeError, match='token cap'):
        await _run(provider, [{'role': 'user', 'content': '问' + '长' * 300},
                              {'role': 'assistant', 'content': '答' + '长' * 300},
                              {'role': 'user', 'content': '查'}],
                   read_tool_executor=lambda name, args: 'ok',
                   compaction=_settings(reserve_tokens=250), summarize=summarize)


async def test_compaction_disabled_by_default():
    """不传 compaction 即关闭：产品行为向后兼容，灰度由接线方决定。"""
    register_model(ModelInfo(id='tiny3', name='T3', context_window=400,
                             max_tokens=256, cost={}))
    provider = CoreAgentStub([
        _tool_response(),
        ModelResponse(stop_reason='stop', text='好。'),
    ])
    provider.model = 'tiny3'
    events = await _run(provider, [{'role': 'user', 'content': '长' * 400}],
                        read_tool_executor=lambda name, args: 'ok')
    second_round = provider.calls[1]
    assert all(not m.get('is_compaction') for m in second_round)
