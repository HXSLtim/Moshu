"""Core Agent P4 七修契约测试（层二 A/B 发现 + provider 四修）。

⑤compact 全线 async（同步签名直调 async summarize 拿 coroutine 的接缝，
测试 stub 全改真 async——await 非 awaitable 即炸，杜绝同步 stub 再遮缝）；
⑥压缩产物组装处剥离 usage（旧 usage 是压缩前大上下文实报，当新锚会
误判二次压缩）；①reasoning_content 显式弃用；②usage 拆 reasoning_tokens；
③length+空 content 可诊断错误；④deepseek 系 ModelInfo 真实参数。
"""
from types import SimpleNamespace as _NS

import pytest

from app.services.conversation.core.compaction import (
    build_post_compaction_messages,
    compact,
    prepare_compaction,
    CompactionSettings,
)
from app.services.conversation.core.models import get_model
from app.services.conversation.core.provider import OpenAIStreamProvider
from tests.test_core_agent_compaction import _settings, _user, _assistant
from tests.test_core_agent_provider import FakeCompletions, _chunk, _tool_delta


# ---------- ⑤ compact 全线 async ----------

async def test_compact_is_async_and_awaits_summarizer():
    async def summarize(messages, previous_summary, custom_instructions=None):
        return '异步摘要'

    messages = [
        _user('问一' + '长' * 60),
        _assistant('答一' + '长' * 60),
        _user('问二' + '长' * 60),
        _assistant('答二' + '长' * 60),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=40))
    result = await compact(preparation, summarize)
    assert isinstance(result['summary'], str) and result['summary'] == '异步摘要'


async def test_compact_split_turn_both_calls_async():
    calls = []

    async def summarize(messages, previous_summary, custom_instructions=None):
        calls.append(1)
        return f'摘要{len(calls)}'

    messages = [
        _user('旧问' + '长' * 60),
        _assistant('旧答' + '长' * 60),
        _user('开轮' + '长' * 100),
        {'role': 'assistant', 'content': '查',
         'tool_calls': [{'id': 'c1', 'type': 'function',
                         'function': {'name': 'read_chapter', 'arguments': '{}'}}]},
        {'role': 'tool', 'tool_call_id': 'c1', 'content': '果' * 100},
        _assistant('轮内答复' + '长' * 100),
        _user('新轮'),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=10))
    result = await compact(preparation, summarize)
    assert len(calls) == 2
    assert '摘要1' in result['summary'] and '摘要2' in result['summary']


async def test_async_summarizer_failure_propagates():
    """async 摘要器抛错照旧透传（截断摘要拒落盘纪律不受 async 化影响）。"""

    async def summarize(messages, previous_summary, custom_instructions=None):
        raise RuntimeError('Summarization failed: generation hit the token cap')

    messages = [_user('问' + '长' * 60), _assistant('答' + '长' * 60), _user('尾')]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=5))
    with pytest.raises(RuntimeError, match='token cap'):
        await compact(preparation, summarize)


# ---------- ⑥ 压缩产物组装处剥离 usage ----------

async def test_post_compaction_messages_strip_usage():
    """保留区旧 usage 是压缩前实报，必须剥离——防二次压缩误锚。"""
    async def summarize(messages, previous_summary, custom_instructions=None):
        return '新摘要'

    messages = [
        _user('问一' + '长' * 60),
        _assistant('答一' + '长' * 60, usage={'input': 500, 'output': 100, 'total': 600}),
        _user('问二' + '长' * 60),
        _assistant('答二' + '长' * 60, usage={'input': 900, 'output': 100, 'total': 1000}),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=40))
    result = await compact(preparation, summarize)
    rebuilt = build_post_compaction_messages(messages, result)
    # 摘要条目带头，保留区随后；全量无 usage 字段。
    assert rebuilt[0].get('is_compaction') is True
    assert rebuilt[0]['summary'] == '新摘要'
    assert all('usage' not in m for m in rebuilt), '压缩产物不得携带旧 usage'
    # 保留区内容原样（内容不丢，只剥计量）。
    kept_original = messages[result['first_kept_index']:]
    assert [m.get('content') for m in rebuilt[1:]] == [m.get('content') for m in kept_original]


def test_post_compaction_strip_is_copy_not_mutation():
    """剥离是产物拷贝，不回改原会话（原对话历史保持真实 usage）。"""
    messages = [
        _user('问一' + '长' * 60),
        _assistant('答一' + '长' * 60, usage={'input': 5, 'output': 1, 'total': 6}),
        _user('问二'),
        _assistant('答二'),
    ]
    result = {'summary': 'S', 'first_kept_index': 2, 'tokens_before': 100}
    rebuilt = build_post_compaction_messages(messages, result)
    assert all('usage' not in m for m in rebuilt)
    assert 'usage' in messages[1]  # 原始未动


# ---------- ① reasoning_content 显式弃用 ----------

async def test_reasoning_content_discarded_not_streamed():
    """DeepSeek 思考型流式 reasoning_content：显式弃用——不进 text 也不产事件
    （官方字段历史不回传，积攒了也无法续传，弃用+日志是唯一正确处置）。"""
    def _delta_chunk(reasoning=None, content=None, finish=None):
        delta = _NS(content=content, tool_calls=None, reasoning_content=reasoning)
        return _NS(choices=[_NS(delta=delta, finish_reason=finish)])

    provider, _ = _provider_with([_delta_chunk(reasoning='思考片段……'),
                                  _delta_chunk(content='正文', finish='stop')])
    events = [e async for e in provider.stream([{'role': 'user', 'content': '写'}])]
    assert [e['type'] for e in events] == ['text_delta', 'response_done']
    assert events[0]['delta'] == '正文'
    assert '思考片段' not in events[-1]['response'].text


def _provider_with(chunks):
    completions = FakeCompletions(chunks)
    provider = OpenAIStreamProvider(client=_NS(chat=_NS(completions=completions)), model='m')
    return provider, completions


# ---------- ② usage 拆 reasoning_tokens ----------

async def test_usage_extracts_reasoning_tokens():
    """completion_tokens_details.reasoning_tokens 拆为 usage.reasoning（output 子集）。"""
    usage = _NS(prompt_tokens=100, completion_tokens=80, total_tokens=180,
                completion_tokens_details=_NS(reasoning_tokens=48))
    provider, _ = _provider_with([
        _chunk(content='答'), _chunk(finish_reason='stop'),
        _NS(choices=[], usage=usage)])
    events = [e async for e in provider.stream([{'role': 'user', 'content': '写'}])]
    response = events[-1]['response']
    assert response.usage == {'input': 100, 'output': 80, 'total': 180, 'reasoning': 48}


# ---------- ③ length + 空 content 可诊断错误 ----------

async def test_length_with_empty_content_becomes_diagnosable_error():
    """思考烧穿 max_tokens：length 且无正文无工具调用——转可诊断错误，
    不再作为「可重发的截断」进拒执行循环（没有可拒的东西，循环会空转）。"""
    def _delta_chunk(reasoning=None, content=None, calls=None, finish=None):
        delta = _NS(content=content, tool_calls=calls, reasoning_content=reasoning)
        return _NS(choices=[_NS(delta=delta, finish_reason=finish)])

    provider, _ = _provider_with([_delta_chunk(reasoning='烧穿全部预算的思考'),
                                  _delta_chunk(finish='length')])
    events = [e async for e in provider.stream([{'role': 'user', 'content': '写'}])]
    response = events[-1]['response']
    assert response.stop_reason == 'error'
    assert '思考' in (response.error_message or '') or '输出' in (response.error_message or '')


async def test_length_with_tool_calls_keeps_reject_path():
    """带工具调用的 length 保持拒执行语义（回模型重发），不受 ③ 影响。"""
    call = _tool_delta(tid='c1', name='read_chapter', arguments='{"chapter": 3}')
    provider, _ = _provider_with([_chunk(tool_calls=[call]), _chunk(finish_reason='length')])
    events = [e async for e in provider.stream([{'role': 'user', 'content': '写'}])]
    assert events[-1]['response'].stop_reason == 'length'


# ---------- ④ deepseek 系 ModelInfo 真实参数 ----------

def test_deepseek_models_registered_with_real_params():
    chat = get_model('deepseek-chat')
    assert chat.context_window == 65536
    assert chat.max_tokens == 8192
    reasoner = get_model('deepseek-reasoner')
    assert reasoner.context_window == 65536
    assert reasoner.max_tokens == 8192
    assert reasoner.supports_usage_in_streaming and reasoner.supports_finish_reason
