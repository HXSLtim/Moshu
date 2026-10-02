"""创作对话应用服务：有界上下文、模型调用与候选输出契约。"""
import asyncio
from typing import Iterable, Literal, TYPE_CHECKING

from app.core.config import settings
from app.services.context.budget import (
    MAX_CHAT_OUTPUT_CHARS,
    build_writing_chat_messages,
)
from app.services.model.provider import create_chat_model
from app.services.model.result import ModelResult, parse_model_result
from app.services.model.execution import invoke_model

if TYPE_CHECKING:
    from app.services.context.builder import ContextPack


class WritingService:
    """生成待审阅回复；对话持久化和终态竞争由调用方处理。"""

    def __init__(self):
        self.llm = create_chat_model(temperature=0.8, max_retries=0)

    def prepare_messages(
        self, *, context_pack: "ContextPack", current_content: str,
        turns: Iterable, instruction: str,
        mode: Literal["discuss", "continue"],
    ) -> list[tuple[str, str]]:
        return build_writing_chat_messages(
            worldview=context_pack.worldview, current_content=current_content,
            story_context="\n".join(context_pack.story_bible_context),
            digest_context=context_pack.digest_context,
            structured_context=context_pack.structured_context,
            turns=turns, instruction=instruction, mode=mode,
        )

    async def reply(self, messages: list[tuple[str, str]]) -> ModelResult:
        """只接受已按预算构建的消息，拒绝不完整或不适用的模型结果。"""
        response = await asyncio.wait_for(
            invoke_model(self.llm, messages),
            timeout=settings.LLM_TIMEOUT_SECONDS * (settings.LLM_MAX_RETRIES + 1),
        )
        return parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS)


writing_service = WritingService()
