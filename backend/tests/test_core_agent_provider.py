"""Core Agent provider 层契约测试：SDK 四纪律 + 统一增量事件面。

纪律对应设计稿 §3.4：①透传不吞不猜(finish_reason 缺失→None，推断归
compat 层，宣称支持却缺失直接报错不静默猜)；②max_retries=0 关内置重试；
③usage 采集走 stream_options，缺席保持 None 不伪造；④降级条件另档不测。
"""
from types import SimpleNamespace

import pytest

from app.services.conversation.core.provider import OpenAIStreamProvider, ProviderCompat


def _chunk(content=None, tool_calls=None, finish_reason=None, usage=None, role=None):
    """构造最小 OpenAI 兼容流式 chunk；provider 只做属性访问。"""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, role=role)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_delta(index=0, tid=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=tid, name=name, arguments=arguments,
                           type='function')


class FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs

        async def gen():
            for item in self._chunks:
                if isinstance(item, BaseException):
                    raise item
                yield item

        return gen()


def _provider(chunks, compat=None):
    completions = FakeCompletions(chunks)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = OpenAIStreamProvider(client=client, model='test-model', compat=compat)
    return provider, completions


async def _collect(provider, messages=None):
    return [event async for event in provider.stream(messages or [{'role': 'user', 'content': 'hi'}])]


async def test_max_retries_zero_disabled_sdk_retry():
    """纪律②：SDK 内置重试必须归零，重试预算全走自控。"""
    captured = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions(
                [_chunk(finish_reason='stop')]))

    import app.services.conversation.core.provider as provider_mod
    original = provider_mod.openai.AsyncClient
    provider_mod.openai.AsyncClient = FakeAsyncClient
    try:
        OpenAIStreamProvider(model='m')
        assert captured.get('max_retries') == 0
    finally:
        provider_mod.openai.AsyncClient = original


async def test_text_deltas_then_done():
    provider, _ = _provider([
        _chunk(role='assistant'),
        _chunk(content='你'),
        _chunk(content='好'),
        _chunk(finish_reason='stop'),
    ])
    events = await _collect(provider)
    assert [e['type'] for e in events] == ['text_delta', 'text_delta', 'response_done']
    done = events[-1]['response']
    assert done.stop_reason == 'stop'
    assert done.text == '你好'
    assert done.usage is None  # 没有 usage 帧：缺席保持 None，不伪造(纪律③)


async def test_usage_frame_collected_when_present():
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5)
    provider, completions = _provider([
        _chunk(content='好'),
        _chunk(finish_reason='stop'),
        SimpleNamespace(choices=[], usage=usage),  # include_usage 的独立 usage 帧
    ])
    events = await _collect(provider)
    assert completions.last_kwargs.get('stream_options') == {'include_usage': True}
    done = events[-1]['response']
    assert done.usage == {'input': 3, 'output': 2, 'total': 5}


async def test_usage_stream_option_off_when_compat_disables():
    provider, completions = _provider(
        [_chunk(content='好'), _chunk(finish_reason='stop')],
        compat=ProviderCompat(supports_usage_in_streaming=False),
    )
    await _collect(provider)
    assert 'stream_options' not in completions.last_kwargs


async def test_toolcall_start_then_delta_events():
    provider, _ = _provider([
        _chunk(tool_calls=[_tool_delta(tid='call_1', name='read_chapter', arguments='{"ch')]),
        _chunk(tool_calls=[_tool_delta(arguments='apter": 3}')]),
        _chunk(finish_reason='tool_calls'),
    ])
    events = await _collect(provider)
    kinds = [e['type'] for e in events]
    assert kinds == ['toolcall_start', 'toolcall_delta', 'toolcall_delta', 'response_done']
    assert events[0]['index'] == 0 and events[0]['id'] == 'call_1' and events[0]['name'] == 'read_chapter'
    assert events[1]['args_delta'] == '{"ch'
    assert events[2]['args_delta'] == 'apter": 3}'
    done = events[-1]['response']
    assert done.stop_reason == 'toolUse'
    assert done.tool_calls == [{'id': 'call_1', 'name': 'read_chapter', 'arguments': {'chapter': 3}}]


async def test_finish_reason_missing_inferred_when_unsupported():
    """纪律①：网关不给 finish_reason 且 compat 声明不支持——有工具调用判 toolUse。"""
    provider, _ = _provider([
        _chunk(tool_calls=[_tool_delta(tid='c1', name='t', arguments='{}')]),
        _chunk(),  # 流直接结束，无 finish_reason
    ], compat=ProviderCompat(supports_finish_reason=False))
    events = await _collect(provider)
    done = events[-1]['response']
    assert done.stop_reason == 'toolUse'
    assert done.finish_reason_raw is None


async def test_finish_reason_missing_inferred_stop_without_tools():
    provider, _ = _provider([_chunk(content='好'), _chunk()],
                            compat=ProviderCompat(supports_finish_reason=False))
    done = (await _collect(provider))[-1]['response']
    assert done.stop_reason == 'stop'


async def test_finish_reason_missing_error_when_declared_supported():
    """纪律①反向：宣称支持却缺失——直接报错，不静默猜。"""
    provider, _ = _provider([_chunk(content='好'), _chunk()], compat=ProviderCompat())
    events = await _collect(provider)
    done = events[-1]['response']
    assert done.stop_reason == 'error'
    assert done.error_message is not None and 'finish_reason' in done.error_message


async def test_length_stop_reason_mapped():
    provider, _ = _provider([_chunk(content='半句'), _chunk(finish_reason='length')])
    done = (await _collect(provider))[-1]['response']
    assert done.stop_reason == 'length'
    assert done.text == '半句'


async def test_sdk_error_becomes_error_response_not_exception():
    """StreamFn 契约：不得抛异常，失败编码为 error 响应。"""
    provider, _ = _provider([RuntimeError('connection reset')])
    events = await _collect(provider)
    assert len(events) == 1
    done = events[0]['response']
    assert done.stop_reason == 'error'
    assert 'connection reset' in done.error_message


async def test_cancelled_becomes_aborted_response():
    """取消不是异常，是一条消息：CancelledError 捕获为 aborted 响应。"""
    import asyncio
    provider, _ = _provider([_chunk(content='半'), asyncio.CancelledError()])
    events = await _collect(provider)
    done = events[-1]['response']
    assert done.stop_reason == 'aborted'
    assert done.text == '半'


async def test_tools_passed_through_to_sdk():
    tools = [{'type': 'function', 'function': {'name': 't', 'parameters': {}}}]
    provider, completions = _provider([_chunk(finish_reason='stop')])
    async for _event in provider.stream([{'role': 'user', 'content': 'hi'}], tools=tools):
        pass
    assert completions.last_kwargs.get('tools') == tools


# ---- 真 SDK 类型流形状回归（2026-10-03 实证：手搓 fake 与实现同错，真 SDK 增量为嵌套 function 形状） ----

def _real_sdk_stream_chunks():
    """用真 openai SDK 类型构造流式工具增量（嵌套 function 形状），杜绝 fake 随实现走。"""
    from openai.types.chat import ChatCompletionChunk
    from openai.types.chat.chat_completion_chunk import (
        Choice, ChoiceDelta, ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction,
    )

    def chunk(delta):
        return ChatCompletionChunk(
            id='cmpl-x', choices=[Choice(index=0, delta=delta, finish_reason=None)],
            created=0, model='deepseek-chat', object='chat.completion.chunk',
        )

    tool_chunks = [
        chunk(ChoiceDelta(tool_calls=[ChoiceDeltaToolCall(
            index=0, id='call_1', type='function',
            function=ChoiceDeltaToolCallFunction(name='search_story_bible', arguments=''),
        )])),
        chunk(ChoiceDelta(tool_calls=[ChoiceDeltaToolCall(
            index=0, function=ChoiceDeltaToolCallFunction(arguments='{"query": "白狐"}'),
        )])),
        chunk(ChoiceDelta(content='找到了。')),
        ChatCompletionChunk(
            id='cmpl-x', choices=[Choice(index=0, delta=ChoiceDelta(),
                                          finish_reason='tool_calls')],
            created=0, model='deepseek-chat', object='chat.completion.chunk',
        ),
    ]

    async def gen():
        for c in tool_chunks:
            yield c

    return gen()


@pytest.mark.asyncio
async def test_real_sdk_nested_toolcall_shape_streamed():
    """真 SDK 形状（name/arguments 嵌套于 call.function）必须产出 toolcall_start 与 delta 事件。"""
    gen = _real_sdk_stream_chunks()

    class RealShapeCompletions:
        async def create(self, **kwargs):
            return gen

    provider = OpenAIStreamProvider(model='deepseek-chat')
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=RealShapeCompletions()))
    events = []
    async for ev in provider.stream([], None):
        events.append(ev)
    starts = [e for e in events if e['type'] == 'toolcall_start']
    deltas = [e for e in events if e['type'] == 'toolcall_delta']
    finals = [e for e in events if e['type'] == 'response_done']
    assert starts and starts[0]['name'] == 'search_story_bible' and starts[0]['id'] == 'call_1'
    assert deltas and deltas[0]['args_delta'] == '{"query": "白狐"}'
    assert finals and finals[0]['response'].stop_reason != 'error'
    assert 'ChoiceDeltaToolCall' not in (finals[0]['response'].error_message or '')
