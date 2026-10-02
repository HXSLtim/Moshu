"""统一文本模型返回值，防止截断内容或工具请求被当作已完成候选。"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True)
class ModelResult:
    """有效正文和提供方实际返回的元数据；缺失的用量不估算。"""

    text: str
    model: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None


class ModelOutputError(ValueError):
    """可向作者展示的输出错误，不包含提供方原始响应或半成品正文。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _mapping(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def model_json_text(text: str) -> str:
    """仅去掉完整单一 JSON 代码块外壳；业务字段、语法及截断仍由严格校验拒绝。"""
    value = text.strip()
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", value)
    return fenced.group(1) if fenced else value


def parse_model_result(response: Any, *, max_output_chars: int) -> ModelResult:
    """只接收完整的非空文本，兼容没有元数据的本地模型响应。

    usage 优先使用 LangChain 标准字段，其次保留提供方 token_usage 原样。
    字符上限是应用预算，不代表精确 token 数，也不会静默裁剪输出。
    """

    if isinstance(max_output_chars, bool) or not isinstance(max_output_chars, int) or max_output_chars <= 0:
        raise ValueError("模型输出字符预算必须是正整数")

    metadata = _mapping(getattr(response, "response_metadata", None))
    additional = _mapping(getattr(response, "additional_kwargs", None))
    # 任一完成字段报告中断就拒绝，不能让另一字段的 stop 或 None 掩盖它。
    reasons = [metadata.get("finish_reason"), metadata.get("stop_reason")]
    finish_reason = next((reason for reason in reasons if reason is not None), None)
    if any(reason is not None and not isinstance(reason, str) for reason in reasons):
        raise ModelOutputError("invalid_finish_reason", "模型未返回有效的完成状态，请重新生成。")

    if any(reason in {"length", "max_tokens", "max_output_tokens"} for reason in reasons):
        raise ModelOutputError("truncated", "模型回复因输出长度限制被截断，请缩短本次生成要求后重试。")
    if "content_filter" in reasons:
        raise ModelOutputError("content_filtered", "模型提供方未能返回完整回复，请调整本次请求后重试。")
    if additional.get("refusal"):
        raise ModelOutputError("refused", "模型未能完成本次请求，请调整请求后重试。")
    if (any(reason in {"tool_calls", "function_call", "tool_use"} for reason in reasons)
            or getattr(response, "tool_calls", None)
            or getattr(response, "invalid_tool_calls", None)
            or additional.get("tool_calls")
            or additional.get("function_call")):
        raise ModelOutputError("tool_call", "模型返回了工具请求，尚未产生可用正文，请重新生成。")
    if any(reason not in {None, "stop", "end_turn", "stop_sequence"} for reason in reasons):
        raise ModelOutputError("incomplete", "模型未确认回复已完成，请重新生成。")

    content = getattr(response, "content", None)
    if not isinstance(content, str):
        raise ModelOutputError("non_text", "模型返回的内容不是文本，请重新生成。")
    if not content.strip():
        raise ModelOutputError("empty", "模型未返回有效内容，请重新生成。")
    if len(content) > max_output_chars:
        raise ModelOutputError("too_long", "模型回复超过本次输出预算，请缩短生成要求后重试。")

    model = metadata.get("model_name") or metadata.get("model")
    if not isinstance(model, str) or not model.strip():
        model = None
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, Mapping) or not usage:
        usage = metadata.get("token_usage")

    return ModelResult(
        text=content.strip(),
        model=model,
        usage=deepcopy(dict(usage)) if isinstance(usage, Mapping) and usage else None,
        finish_reason=finish_reason,
    )
