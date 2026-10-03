"""Core Agent P2 契约测试：Model 元数据面 + 预算三口径(次数/token/钱)。

设计稿 §3.4：per-model maxTokens/contextWindow/成本进静态元数据；预算守卫
从「次数」单口径升级三口径——一期次数+token，钱随 Usage cost 就绪即开。
usage 缺席(None，网关不给)时 token/钱口径跳过不误判——null 不伪造纪律的
预算侧。
"""
import pytest

from app.services.conversation.core.budget import BudgetExceeded, CoreBudget
from app.services.conversation.core.models import ModelInfo, get_model, register_model
from app.services.conversation.core.types import ModelResponse


# ---------- Model 元数据面 ----------

def test_default_registry_has_production_models():
    model = get_model(None)  # 缺省模型(生产主模型)
    assert model.context_window > 0
    assert model.max_tokens > 0
    assert model.max_tokens <= model.context_window


def test_registry_lookup_and_fallback():
    assert get_model(None) is not None
    assert get_model('不存在的模型') is get_model(None)  # 未知名回退缺省而非崩溃


def test_register_model_overrides():
    info = ModelInfo(id='spike-model', name='Spike', context_window=8192,
                     max_tokens=2048, cost={'input': 1.0, 'output': 2.0})
    register_model(info)
    assert get_model('spike-model').max_tokens == 2048


def test_model_info_cost_per_million_semantics():
    """cost 单位=每百万 token 美元；预算侧按 usage 换算。"""
    model = get_model(None)
    assert all(value >= 0 for value in model.cost.values())


# ---------- 预算三口径 ----------

def _usage(total, inp=None, out=None):
    return {'input': inp if inp is not None else total // 2,
            'output': out if out is not None else total - total // 2,
            'total': total}


def test_call_budget_still_enforced():
    budget = CoreBudget(max_model_calls=2)
    budget.record_call(usage=None)
    budget.record_call(usage=None)
    with pytest.raises(BudgetExceeded):
        budget.check(total_calls=2)


def test_token_budget_enforced():
    budget = CoreBudget(max_model_calls=10, max_total_tokens=1000)
    budget.record_call(usage=_usage(600))
    budget.check(total_calls=1)  # 未超
    budget.record_call(usage=_usage(600))
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.check(total_calls=2)
    assert 'token' in str(exc_info.value)


def test_token_budget_skipped_when_usage_missing():
    """网关不给 usage(None 不伪造)：token 口径跳过，不误判也不虚计。"""
    budget = CoreBudget(max_model_calls=10, max_total_tokens=100)
    budget.record_call(usage=None)
    budget.record_call(usage=None)
    budget.check(total_calls=2)  # 不抛


def test_cost_budget_enforced_when_model_cost_ready():
    cost = {'input': 1.0, 'output': 2.0}  # $/M tokens
    budget = CoreBudget(max_model_calls=10, max_cost_usd=0.001, model_cost=cost)
    # usage: input=400k? 换算：cost = 400000*1/M*1 + 400000*2/M*2? 逐次计：
    budget.record_call(usage=_usage(1_000_000, inp=600_000, out=400_000))
    # 花费 = 600000/1e6*1.0 + 400000/1e6*2.0 = 0.6 + 0.8 = 1.4 > 0.001
    with pytest.raises(BudgetExceeded) as exc_info:
        budget.check(total_calls=1)
    assert '成本' in str(exc_info.value) or 'cost' in str(exc_info.value)


def test_cost_budget_dormant_without_model_cost():
    """cost 未配置(钱未就绪)：口径休眠，同 usage=None 一样不误判。"""
    budget = CoreBudget(max_model_calls=10, max_cost_usd=0.001, model_cost=None)
    budget.record_call(usage=_usage(10_000_000))
    budget.check(total_calls=1)


def test_budget_snapshot_reports_all_tracks():
    budget = CoreBudget(max_model_calls=10, max_total_tokens=5000,
                        model_cost={'input': 1.0, 'output': 2.0})
    budget.record_call(usage=_usage(1000, inp=600, out=400))
    snapshot = budget.snapshot(total_calls=1)
    assert snapshot['model_calls'] == 1
    assert snapshot['total_tokens'] == 1000
    assert snapshot['cost_usd'] == pytest.approx(600 / 1e6 * 1.0 + 400 / 1e6 * 2.0)


# ---------- 接线：loop 挂预算检查点、provider 接元数据 ----------

from app.services.conversation.core.loop import run_core_agent
from app.services.conversation.core.models import register_model
from tests.test_core_agent_loop import SPEC, ScriptedProvider, _call, _resp


async def test_loop_records_usage_into_budget():
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 1})],
              usage={'input': 500, 'output': 100, 'total': 600}),
        _resp(text='答', usage={'input': 300, 'output': 100, 'total': 400}),
    ])

    async def read_executor(name, args):
        return 'ok'

    budget = CoreBudget(max_model_calls=10, max_total_tokens=5000,
                        model_cost={'input': 1.0, 'output': 2.0})
    final_events = []
    async for event in run_core_agent(provider, [{'role': 'user', 'content': 'x'}],
                                      tools_spec=SPEC, read_tool_executor=read_executor,
                                      budget=budget):
        final_events.append(event)
    snapshot = budget.snapshot(total_calls=2)
    assert snapshot['total_tokens'] == 1000
    assert snapshot['cost_usd'] == pytest.approx(800 / 1e6 * 1.0 + 200 / 1e6 * 2.0)


async def test_loop_budget_token_exceeded_raises_mid_run():
    """第二轮前 token 已超：loop 检查点拦下，不发起第三次调用。"""
    provider = ScriptedProvider([
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 1})],
              usage={'input': 900, 'output': 100, 'total': 1000}),
        _resp(stop_reason='toolUse', tool_calls=[_call('read_chapter', {'chapter': 2})],
              usage={'input': 900, 'output': 100, 'total': 1000}),
    ])

    async def read_executor(name, args):
        return 'ok'

    budget = CoreBudget(max_model_calls=10, max_total_tokens=1500)
    with pytest.raises(BudgetExceeded):
        async for _ in run_core_agent(provider, [{'role': 'user', 'content': 'x'}],
                                      tools_spec=SPEC, read_tool_executor=read_executor,
                                      budget=budget):
            pass
    assert len(provider.requests) == 2  # 第三次调用被预算拦下


async def test_budget_exceeded_is_execution_budget_error_family():
    """消费层(except ExecutionBudgetError)统一可捕——异常族不裂。"""
    from app.services.model.execution import ExecutionBudgetError
    assert issubclass(BudgetExceeded, ExecutionBudgetError)


async def test_provider_uses_model_info_max_tokens():
    from types import SimpleNamespace
    from app.services.conversation.core.provider import OpenAIStreamProvider
    register_model(ModelInfo(id='spike-77', name='S', context_window=32768, max_tokens=777))
    completions = type('C', (), {})()
    from tests.test_core_agent_provider import FakeCompletions
    fake = FakeCompletions([])
    provider = OpenAIStreamProvider(
        client=SimpleNamespace(chat=SimpleNamespace(completions=fake)), model='spike-77')
    assert provider.max_tokens == 777
