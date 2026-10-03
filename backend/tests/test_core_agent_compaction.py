"""Core Agent P3 契约测试：压缩链(计量/切点/摘要/失败纪律) + 预算重设计
(三层上下文模型+比例制 reserve)。

设计稿 §3.2+§3.4 预算重设计：chars/3 估算(选型会⑤)、keepRecent=32000、
reserve=max(window×20%, 16384) 下限、Session 层下限与 keepRecent 联动、
切点绝不破工具对、isSplitTurn 单独 turn-prefix 摘要、截断摘要拒落盘。
"""
import pytest

from app.services.conversation.core.compaction import (
    CompactionSettings,
    compact,
    estimate_context_tokens,
    estimate_message_tokens,
    find_cut_point,
    prepare_compaction,
    should_compact,
)
from app.services.conversation.core.context_budget import ContextBudgetPlan
from app.services.conversation.core.types import ModelResponse


def _user(text):
    return {'role': 'user', 'content': text}


def _assistant(text, usage=None):
    message = {'role': 'assistant', 'content': text}
    if usage is not None:
        message['usage'] = usage
    return message


def _tool_call(id_='c1', name='read_chapter'):
    return {'id': id_, 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}


def _assistant_with_calls(text, calls):
    return {'role': 'assistant', 'content': text, 'tool_calls': calls}


def _tool(id_, content):
    return {'role': 'tool', 'tool_call_id': id_, 'content': content}


# ---------- 计量：chars/3 估算 + 混合口径 ----------

def test_estimate_message_tokens_chars_per_three():
    # 30 个汉字 → 30/3=10 token(中文系数起步，选型会⑤)。
    assert estimate_message_tokens(_user('字' * 30)) == 10


def test_estimate_mixed_last_usage_plus_tail_estimate():
    """混合计量：最后有效 assistant usage 实报 + 其后消息 chars/3 补尾。"""
    messages = [
        _user('前言' * 20),                       # 40 chars → 估 14
        _assistant('回答' * 20, usage={'input': 500, 'output': 100, 'total': 600}),
        _user('尾巴' * 30),                        # 60 chars → 估 20
    ]
    estimate = estimate_context_tokens(messages)
    assert estimate['tokens'] == 600 + 20
    assert estimate['usage_tokens'] == 600
    assert estimate['trailing_tokens'] == 20


def test_estimate_all_estimate_when_no_usage():
    messages = [_user('问' * 30), _assistant('答' * 30)]
    estimate = estimate_context_tokens(messages)
    assert estimate['usage_tokens'] == 0
    assert estimate['tokens'] == 20  # 全量 chars/3


def test_estimate_skips_aborted_error_zero_usage():
    """aborted/error/全零 usage 不采信——退化为其后消息全量估算。"""
    messages = [
        _assistant('旧回答', usage={'input': 0, 'output': 0, 'total': 0}),
        _user('新问' * 15),
    ]
    estimate = estimate_context_tokens(messages)
    assert estimate['usage_tokens'] == 0
    assert estimate['tokens'] == 11  # 旧回答 3 字符(1) + 新问 30 字符(10)


# ---------- 触发 ----------

def test_should_compact_threshold():
    settings = CompactionSettings(enabled=True, reserve_tokens=16384, keep_recent_tokens=32000)
    assert should_compact(110000, 131072, settings) is False  # 110000 < 114688
    assert should_compact(115000, 128000, settings) is True   # 115000 > 111616


def test_should_compact_disabled():
    settings = CompactionSettings(enabled=False)
    assert should_compact(999999, 1000, settings) is False


# ---------- 切点纪律 ----------

def test_cut_point_never_between_tool_and_its_call():
    """切点绝不落在 tool 结果与其 assistant 调用之间。"""
    messages = [
        _user('问' * 300),
        _assistant_with_calls('查', [_tool_call('c1'), _tool_call('c2')]),
        _tool('c1', '结' * 300),
        _tool('c2', '果' * 300),
        _user('继续' * 300),
        _assistant('答' * 300),
    ]
    result = find_cut_point(messages, keep_recent_tokens=50)
    # 50 token 只够尾部；切点必须吸附到合法边界(user/assistant)，不在 tool 上。
    assert messages[result['first_kept_index']]['role'] != 'tool'
    if result['first_kept_index'] > 0:
        # 切点前一条不能是「已切开的 assistant 调用而其 tool 结果被留在保留区外」
        # ——若切在 assistant(带 tool_calls) 上，其 tool 结果必须跟入保留区。
        boundary = messages[result['first_kept_index']]
        if boundary['role'] == 'assistant' and boundary.get('tool_calls'):
            kept = messages[result['first_kept_index']:]
            kept_tool_ids = {m['tool_call_id'] for m in kept if m['role'] == 'tool'}
            assert {c['id'] for c in boundary['tool_calls']} <= kept_tool_ids


def test_split_turn_detected_when_cut_inside_turn():
    """切点落在轮中间(assistant 与下一 user 之间无边界可吸附)→isSplitTurn。"""
    messages = [
        _user('开轮' * 100),
        _assistant_with_calls('查', [_tool_call()]),
        _tool('c1', '果' * 100),
        _assistant('轮内答复' * 100),
    ]
    result = find_cut_point(messages, keep_recent_tokens=40)
    assert result['is_split_turn'] is True
    assert result['turn_start_index'] == 0  # 被切开轮次的 user 起点定位


def test_cut_point_keeps_recent_budget():
    messages = [_user(f'第{i}轮' + '长' * 90) for i in range(10)]
    messages.append(_assistant('最新回答' + '好' * 120))
    result = find_cut_point(messages, keep_recent_tokens=60)
    kept = messages[result['first_kept_index']:]
    kept_tokens = sum(estimate_message_tokens(m) for m in kept)
    # 从新往回累积：保留区不显著超过预算(允许最后一条越线)。
    assert kept_tokens - estimate_message_tokens(kept[-1]) < 60


# ---------- prepare + compact ----------

def _settings(**overrides):
    defaults = dict(enabled=True, reserve_tokens=16384, keep_recent_tokens=32000)
    defaults.update(overrides)
    return CompactionSettings(**defaults)


def test_prepare_returns_none_when_compact_boundary_at_tail():
    """上一条已是压缩摘要(无需再压)→prepare 返回 None。"""
    messages = [{'role': 'system', 'content': '摘要占位', 'is_compaction': True},
                _user('问'), _assistant('答')]
    assert prepare_compaction(messages, _settings()) is None


def test_prepare_collects_messages_to_summarize_and_previous():
    messages = [
        {'role': 'system', 'content': '前次摘要', 'is_compaction': True, 'summary': '前情…'},
        _user('问1' + '长' * 60),
        _assistant('答1' + '长' * 60, usage={'input': 400, 'output': 50, 'total': 450}),
        _user('问2' + '长' * 60),
        _assistant('答2' + '长' * 60),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=15))
    assert preparation is not None
    assert preparation['previous_summary'] == '前情…'
    # 被摘要区不含 system(压缩检查点)与保留区。
    summarized_roles = [m['role'] for m in preparation['messages_to_summarize']]
    assert 'system' not in summarized_roles
    assert preparation['messages_to_summarize']  # 有内容可摘
    assert 'first_kept_index' in preparation


def test_compact_uses_injected_summarizer_with_update_semantics():
    received = {}

    def summarize(messages, previous_summary, custom_instructions=None):
        received['messages'] = messages
        received['previous'] = previous_summary
        return '新摘要：保章号/设定键/剧情指针'

    messages = [
        _user('问1' + '长' * 60),
        _assistant('答1' + '长' * 60),
        _user('问2' + '长' * 60),
        _assistant('答2' + '长' * 60),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=40))
    result = compact(preparation, summarize)
    assert result['summary'] == '新摘要：保章号/设定键/剧情指针'
    assert received['previous'] is None  # 无前次摘要走初始模板路径
    assert 'tokens_before' in result and result['tokens_before'] > 0


def test_compact_update_prompt_receives_previous_summary():
    def summarize(messages, previous_summary, custom_instructions=None):
        assert previous_summary == '旧摘要'
        return '合并后的新摘要'

    messages = [
        {'role': 'system', 'content': '旧摘要', 'is_compaction': True, 'summary': '旧摘要'},
        _user('问一' + '长' * 60),
        _assistant('答一' + '长' * 60),
        _user('问二' + '长' * 60),
        _assistant('答二' + '长' * 60),
        _user('尾问'),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=30))
    result = compact(preparation, summarize)
    assert result['summary'] == '合并后的新摘要'


def test_compact_split_turn_appends_turn_prefix_section():
    calls = []

    def summarize(messages, previous_summary, custom_instructions=None):
        calls.append([m.get('content', '')[:6] for m in messages])
        return f'摘要{len(calls)}'

    messages = [
        _user('旧问' + '长' * 60),
        _assistant('旧答' + '长' * 60),
        _user('开轮' + '长' * 100),
        _assistant_with_calls('查', [_tool_call()]),
        _tool('c1', '果' * 100),
        _assistant('轮内答复' + '长' * 100),
        _user('新轮'),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=10))
    assert preparation is not None
    result = compact(preparation, summarize)
    # split turn：主摘要+turn prefix 两次调用合并。
    assert len(calls) == 2
    assert '摘要1' in result['summary'] and '摘要2' in result['summary']


# ---------- 失败纪律：截断摘要拒落盘 ----------

def test_summarizer_truncated_result_rejected():
    """摘要命中输出上限(截断)→压缩失败，残缺文本不得成为会话检查点。"""
    def summarize(messages, previous_summary, custom_instructions=None):
        raise RuntimeError('Summarization failed: generation hit the token cap')

    messages = [
        _user('问' + '长' * 60),
        _assistant('答' + '长' * 60),
        _user('尾'),
    ]
    preparation = prepare_compaction(messages, _settings(keep_recent_tokens=5))
    with pytest.raises(RuntimeError, match='token cap'):
        compact(preparation, summarize)


# ---------- 预算重设计：三层上下文模型 + 比例制 reserve ----------

def test_output_reserve_takes_max_of_ratio_and_floor():
    plan = ContextBudgetPlan.for_window(131072, trust='default')
    assert plan.output_reserve == max(int(131072 * 0.20), 16384)  # 26214


def test_output_reserve_floor_applies_on_small_window():
    plan = ContextBudgetPlan.for_window(32768, trust='default')  # 20%=6553 < 16384
    assert plan.output_reserve == 16384


def test_output_reserve_low_trust_cap_30_percent():
    """低信任网关可上调至 30% 上限(设计稿 pm 合成裁决)。"""
    plan = ContextBudgetPlan.for_window(131072, trust='low')
    assert plan.output_reserve == int(131072 * 0.30)  # 39321


def test_session_floor_linked_to_keep_recent():
    plan = ContextBudgetPlan.for_window(131072, keep_recent_tokens=32000)
    assert plan.session_cap >= 32000  # Session 层下限=keepRecent


def test_session_floor_shrinks_on_small_window():
    """小窗模型(LM Studio 8k/32k)联动缩小：session 不挤出 persistent 与输出。"""
    plan = ContextBudgetPlan.for_window(8192, keep_recent_tokens=32000)
    assert plan.session_cap < 32000
    assert plan.session_cap > 0
    assert plan.persistent_cap > 0
    assert plan.output_reserve <= 8192 // 2  # 输出不吞掉大半窗口


def test_three_layers_sum_within_window():
    for window in (8192, 32768, 131072):
        plan = ContextBudgetPlan.for_window(window, keep_recent_tokens=32000)
        total = plan.persistent_cap + plan.session_cap + plan.ephemeral_cap
        assert total <= window
        assert plan.ephemeral_cap > 0  # 余量层永不为负


def test_persistent_layer_ratio_band():
    plan = ContextBudgetPlan.for_window(131072)
    assert int(131072 * 0.05) <= plan.persistent_cap <= int(131072 * 0.15)


# ---------- 摘要生产端：provider.complete + 失败纪律包装 ----------

from types import SimpleNamespace as _NS

from app.services.conversation.core.compaction import make_provider_summarizer
from tests.test_core_agent_provider import _chunk


class FakeComplete:
    """非流式假端：create 直接返回响应对象(非流式形状)。"""

    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self.response


def _completion(text, finish, usage=None):
    return _NS(choices=[_NS(message=_NS(content=text), finish_reason=finish)], usage=usage)


async def test_provider_complete_returns_model_response():
    from app.services.conversation.core.provider import OpenAIStreamProvider
    usage = _NS(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    fake = FakeComplete(_completion('完整摘要', 'stop', usage))
    provider = OpenAIStreamProvider(client=_NS(chat=_NS(completions=fake)))
    response = await provider.complete([{'role': 'user', 'content': '总结'}])
    assert response.stop_reason == 'stop'
    assert response.text == '完整摘要'
    assert response.usage == {'input': 10, 'output': 5, 'total': 15}
    assert fake.last_kwargs.get('stream') is False


async def test_summarizer_length_rejected_with_token_cap_message():
    from app.services.conversation.core.provider import OpenAIStreamProvider
    fake = FakeComplete(_completion('半截摘要', 'length'))
    provider = OpenAIStreamProvider(client=_NS(chat=_NS(completions=fake)))
    summarize = make_provider_summarizer(provider)
    with pytest.raises(RuntimeError, match='token cap'):
        await summarize([_user('问'), _assistant('答')], None)


async def test_summarizer_error_rejected():
    from app.services.conversation.core.provider import OpenAIStreamProvider

    class Failing:
        async def create(self, **kwargs):
            raise RuntimeError('gateway 502')

    provider = OpenAIStreamProvider(client=_NS(chat=_NS(completions=Failing())))
    summarize = make_provider_summarizer(provider)
    with pytest.raises(RuntimeError, match='failed'):
        await summarize([_user('问')], '旧摘要')


async def test_summarizer_prompt_contains_localized_template():
    from app.services.conversation.core.provider import OpenAIStreamProvider
    captured = {}

    class Capturing(FakeComplete):
        async def create(self, **kwargs):
            captured.update(kwargs)
            return self.response

    fake = Capturing(_completion('六节摘要', 'stop'))
    provider = OpenAIStreamProvider(client=_NS(chat=_NS(completions=fake)))
    summarize = make_provider_summarizer(provider)
    result = await summarize([_user('写第三章')], None)
    assert result == '六节摘要'
    prompt = str(captured.get('messages'))
    # 六节骨架 + Nai 本地化「保章号/设定账本键/剧情指针」入模板。
    for section in ('Goal', 'Key Decisions', 'Next Steps', 'Critical Context'):
        assert section in prompt
    assert '章号' in prompt and '设定账本键' in prompt and '剧情指针' in prompt
