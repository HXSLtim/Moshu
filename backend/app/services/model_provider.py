"""统一构造 OpenAI 兼容模型客户端，业务调用方只选择模型、温度与输出预算。"""

from langchain_openai import ChatOpenAI

from app.core.config import settings


def create_chat_model(
    *,
    model: str | None = None,
    temperature: float = 0.8,
    max_tokens: int | None = None,
    max_retries: int | None = None,
) -> ChatOpenAI:
    """为调用方创建独立客户端；输入上下文仍由 context_budget 约束。"""

    output_budget = settings.LLM_MAX_OUTPUT_TOKENS if max_tokens is None else max_tokens
    if isinstance(output_budget, bool) or not isinstance(output_budget, int) or output_budget <= 0:
        raise ValueError("模型输出预算 max_tokens 必须为正整数")

    reasoning_options = {"model_kwargs": {"reasoning_effort": settings.LLM_REASONING_EFFORT}} if settings.LLM_REASONING_EFFORT else {}
    return ChatOpenAI(
        model=settings.OPENAI_MODEL_COMPLEX if model is None else model,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_API_BASE,
        temperature=temperature,
        max_tokens=output_budget,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES if max_retries is None else max_retries,
        **reasoning_options,
    )
