"""
网文编辑Agent服务
提供对单章内容的轻量编辑审核（节奏、爽点、信息量、重复度等），不做违规/敏感内容审核。
"""
import json
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.services.model_provider import create_chat_model
from app.services.model_result import parse_model_result
from app.services.context_budget import MAX_CHAT_OUTPUT_CHARS, compact_text
from langchain.prompts import ChatPromptTemplate
from loguru import logger

from app.core.config import settings
from app.models.schemas import EditorReview
from app.models.novel import Novel, Chapter


EditorText = Annotated[str, Field(min_length=1)]


class EditorIssuePayload(BaseModel):
    """编辑问题必须有明确类型、级别和描述，不能丢弃损坏条目。"""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    type: EditorText
    level: Literal["info", "warn"]
    message: EditorText
    suggestion: EditorText | None = None


class EditorReviewPayload(BaseModel):
    """模型必须提供完整评价，缺失内容不能由固定好评补齐。"""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    score: int = Field(ge=0, le=100)
    summary: EditorText
    issues: list[EditorIssuePayload]
    suggested_tags: list[EditorText]


class EditorService:
    """网文编辑Agent服务类"""

    def __init__(self) -> None:
        # 复用相对便宜的简单模型，用于轻量点评
        self.llm = create_chat_model(
            model=settings.OPENAI_MODEL_SIMPLE,
            temperature=0.5,
        )

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是一名资深中文网文编辑，只做内容质量与节奏方面的轻量点评，不做任何法律或敏感内容审核。

请根据作者当前这一章的内容，从以下维度给出简明、可执行的建议：
- 节奏：是否拖沓、推进是否够快；
- 爽点/冲突：是否有足够的矛盾和爽点；
- 信息量：是否堆设定/解释过多；
- 重复度：是否有明显的内容/表达重复；
- 人物表现：主角和关键角色是否有鲜明表现。

输出时请严格使用 JSON 格式，结构如下（示例，仅说明字段，不是内容）：
{{
  "score": 85,
  "summary": "整体节奏较为流畅，但开头略慢，可适当前置冲突。",
  "issues": [
    {{
      "type": "节奏",
      "level": "warn",
      "message": "开场连续三段内心独白，缺少外部动作描写。",
      "suggestion": "可以删减部分心理描写，在前两页内安排一个小冲突或事件。"
    }}
  ],
  "suggested_tags": ["爽文", "学院流" ]
}}

score 必须是 0 到 100 的整数，summary 不得为空；issues 和 suggested_tags 必须是数组，没有条目时返回空数组。
每条问题的 type 和 message 不得为空，level 仅允许 info 或 warn；suggestion 可以是非空建议或 null。
不要输出任何解释文字或前后缀，只输出 JSON。""",
                ),
                (
                    "user",
                    """小说标题：{title}
小说类型：{genre}
世界观节选：{worldview}

当前章节：第 {chapter_number} 章《{chapter_title}》
章节内容：
{chapter_content}
""",
                ),
            ]
        )

    async def review_chapter(self, *, novel: Novel, chapter: Chapter) -> Optional[EditorReview]:
        """对单章内容进行轻量审核，返回编辑点评结果。

        若模型返回格式异常或调用失败，返回 None，不影响业务流程。
        """
        # 章节内容过长时做截断，防止提示过大
        content = compact_text(chapter.content, 6000, keep="tail")
        worldview = compact_text(novel.worldview, 800, keep="head")

        chain = self.prompt | self.llm

        try:
            result = await chain.ainvoke(
                {
                    "title": compact_text(novel.title, 200),
                    "genre": compact_text(novel.genre, 50) or "未指定",
                    "worldview": worldview or "未设定",
                    "chapter_number": chapter.chapter_number,
                    "chapter_title": compact_text(chapter.title, 200),
                    "chapter_content": content or "(本章暂无内容)",
                }
            )

            raw = parse_model_result(result, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text

            payload = EditorReviewPayload.model_validate(json.loads(raw))
            return EditorReview(
                **payload.model_dump(),
                created_at=datetime.utcnow(),
            )

        except Exception as e:  # noqa: BLE001
            logger.warning(f"编辑Agent调用失败（novel_id={novel.id}, chapter_id={chapter.id}）: {e}")
            return None


# 单例实例，供路由直接使用
editor_service = EditorService()
