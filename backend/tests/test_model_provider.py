"""共享模型工厂的配置和输出预算契约测试，不访问真实模型服务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import model_provider


@pytest.fixture
def model_factory(monkeypatch):
    """使用独立配置验证真实工厂，不读取或改写本地模型连接。"""

    configuration = SimpleNamespace(
        OPENAI_MODEL_COMPLEX="测试复杂模型",
        OPENAI_API_KEY="测试密钥",
        OPENAI_API_BASE="http://model.test/v1",
        LLM_MAX_OUTPUT_TOKENS=4096,
        LLM_TIMEOUT_SECONDS=37.5,
        LLM_MAX_RETRIES=0,
        LLM_REASONING_EFFORT=None,
    )
    constructor = Mock()
    monkeypatch.setattr(model_provider, "settings", configuration)
    monkeypatch.setattr(model_provider, "ChatOpenAI", constructor)
    return configuration, constructor


def test_defaults_use_shared_connection_and_runtime_limits(model_factory):
    """默认策略继承连接、复杂模型和运行限制，零重试设置不可被覆盖。"""

    _, constructor = model_factory

    client = model_provider.create_chat_model()

    assert client is constructor.return_value
    constructor.assert_called_once_with(
        model="测试复杂模型",
        api_key="测试密钥",
        base_url="http://model.test/v1",
        temperature=0.8,
        max_tokens=4096,
        timeout=37.5,
        max_retries=0,
    )


@pytest.mark.parametrize("budget", [1, 1024, 8192])
def test_explicit_task_profile_preserves_model_temperature_and_budget(model_factory, budget):
    """调用方选择的模型、零温度和正预算不会被默认策略替换或裁剪。"""

    _, constructor = model_factory

    model_provider.create_chat_model(model="测试简单模型", temperature=0.0, max_tokens=budget)

    kwargs = constructor.call_args.kwargs
    assert kwargs["model"] == "测试简单模型"
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == budget
    assert kwargs["timeout"] == 37.5
    assert kwargs["max_retries"] == 0


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "1024"])
def test_invalid_explicit_budget_fails_before_client_creation(model_factory, budget):
    """非法预算应在初始化阶段失败，不能意外退回默认预算后调用模型。"""

    _, constructor = model_factory

    with pytest.raises(ValueError, match="max_tokens 必须为正整数"):
        model_provider.create_chat_model(max_tokens=budget)

    constructor.assert_not_called()


def test_optional_reasoning_setting_is_explicit_provider_payload(model_factory):
    """可选推理参数进入兼容接口请求，未配置时不强加给其他提供方。"""
    configuration, constructor = model_factory
    configuration.LLM_REASONING_EFFORT = "none"
    model_provider.create_chat_model()
    assert constructor.call_args.kwargs["model_kwargs"] == {"reasoning_effort": "none"}


def test_invalid_configured_budget_is_rejected(model_factory):
    """环境中的非法默认预算也必须在模型请求前被发现。"""

    configuration, constructor = model_factory
    configuration.LLM_MAX_OUTPUT_TOKENS = 0

    with pytest.raises(ValueError, match="max_tokens 必须为正整数"):
        model_provider.create_chat_model()

    constructor.assert_not_called()
