"""Core Agent 模型元数据注册表：per-model 静态元数据(设计稿 §3.4)。

替代全局 LLM_MAX_OUTPUT_TOKENS 单值(4096→8192 的教训制度化)：每个模型
自带 context_window/max_tokens(请求级输出预算)/cost(每百万 token 美元)。
未知名回退缺省模型而非崩溃——模型名来自网关配置，宽进严出。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    """一个模型的静态元数据；对齐 pi Model 的墨枢子集。"""
    id: str
    name: str
    context_window: int
    max_tokens: int
    cost: dict = field(default_factory=dict)  # {'input','output'} $/M tokens
    supports_usage_in_streaming: bool = True
    supports_finish_reason: bool = True


# 生产双端点的已知面；LM Studio 本地模型无计费。
# deepseek 系参数=官方 api-docs(quick_start/pricing, 2026-10 核)：上下文 1M、
# 官方输出上限 384K；max_tokens 字段记 Nai 请求级输出预算档(8k, 产品口径)，
# 非官方能力上限。ux v4 实证 123k+ 输入成功与 1M 一致，64k 旧口径作废。
# flash 定价=typingmind 计算器口径($0.0983/$0.1966)，候官方页复核。
_DEFAULT = ModelInfo(
    id='default', name='缺省(跟随 settings.OPENAI_MODEL_COMPLEX)',
    context_window=131072, max_tokens=8192,
    cost={'input': 0.0, 'output': 0.0})
_DEEPSEEK_CHAT = ModelInfo(
    id='deepseek-chat', name='DeepSeek Chat',
    context_window=1048576, max_tokens=8192,
    cost={'input': 0.27, 'output': 1.10})
_DEEPSEEK_REASONER = ModelInfo(
    id='deepseek-reasoner', name='DeepSeek Reasoner(思考型)',
    context_window=1048576, max_tokens=8192,
    cost={'input': 0.55, 'output': 2.19})
_DEEPSEEK_FLASH = ModelInfo(
    id='deepseek-flash', name='DeepSeek Flash(轻量档)',
    context_window=1048576, max_tokens=8192,
    cost={'input': 0.0983, 'output': 0.1966})

_REGISTRY: dict[str, ModelInfo] = {
    _DEFAULT.id: _DEFAULT,
    _DEEPSEEK_CHAT.id: _DEEPSEEK_CHAT,
    _DEEPSEEK_REASONER.id: _DEEPSEEK_REASONER,
    _DEEPSEEK_FLASH.id: _DEEPSEEK_FLASH,
}


def register_model(info: ModelInfo) -> None:
    """注册/覆盖一个模型元数据；同名后写胜出。"""
    _REGISTRY[info.id] = info


def get_model(model_id: str | None) -> ModelInfo:
    """按名取模型；未注册名回退缺省模型(不崩溃，网关配置宽进)。"""
    if model_id and model_id in _REGISTRY:
        return _REGISTRY[model_id]
    return _REGISTRY[_DEFAULT.id]
