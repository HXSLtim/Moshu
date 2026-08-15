"""AI 上下文预算工具。

所有进入模型、日志和工作流追踪的长文本都应先经过这里收敛，避免各路由
各自截断后产生不一致的上下文边界。
"""

from __future__ import annotations

import hashlib
from typing import Iterable, List, Optional


MAX_GENERATION_PROMPT_CHARS = 4_000
MAX_CURRENT_CONTENT_CHARS = 50_000
MAX_WORLDVIEW_CONTEXT_CHARS = 1_200
MAX_STORY_CONTEXT_CHARS = 1_600
MAX_STORY_BIBLE_CONTEXT_CHARS = 1_400
MAX_PLOT_HINT_CHARS = 600
MAX_RAG_QUERY_CHARS = 1_000
MAX_TRACE_PREVIEW_CHARS = 120

MAX_REVIEW_CONTENT_CHARS = 20_000
MAX_REVIEW_PREVIOUS_CHAPTERS = 3
MAX_REVIEW_PREVIOUS_CHAPTER_CHARS = 2_500
MAX_REVIEW_PREVIOUS_TOTAL_CHARS = 6_000

_OMISSION_MARKER = "\n……（上下文已按预算裁剪）……\n"


def compact_text(
    value: Optional[str],
    max_chars: int,
    *,
    keep: str = "both",
) -> str:
    """将文本压缩到字符预算内。

    ``both`` 同时保留开头和结尾，适合章节正文；``head`` 和 ``tail``
    分别适合设定说明与最近剧情。
    """

    text = value or ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if keep == "head":
        return text[:max_chars]
    if keep == "tail":
        return text[-max_chars:]

    marker = _OMISSION_MARKER
    if len(marker) >= max_chars:
        return text[:max_chars]
    remaining = max_chars - len(marker)
    head_length = remaining // 2
    tail_length = remaining - head_length
    return f"{text[:head_length]}{marker}{text[-tail_length:]}"


def ensure_generation_prompt_budget(prompt: str) -> str:
    """验证直接生成提示词，超限时拒绝而不是静默改变用户意图。"""

    normalized = prompt.strip()
    if not normalized:
        raise ValueError("剧情提示词不能为空")
    if len(normalized) > MAX_GENERATION_PROMPT_CHARS:
        raise ValueError(
            f"剧情提示词不能超过 {MAX_GENERATION_PROMPT_CHARS} 个字符"
        )
    return normalized


def build_rag_query(prompt: str) -> str:
    """生成有界 RAG 查询，优先保留最近的创作要求。"""

    return compact_text(prompt, MAX_RAG_QUERY_CHARS, keep="tail")


def build_story_bible_context(
    facts: Iterable[object],
    events: Iterable[object],
) -> List[str]:
    """把已确认的事实与事件压缩成可注入模型的有界上下文。"""

    lines: List[str] = []

    for fact in facts:
        subject = str(getattr(fact, "subject", "")).strip()
        attribute = str(getattr(fact, "attribute", "")).strip()
        value = str(getattr(fact, "value", "")).strip()
        if not subject or not attribute or not value:
            continue
        line = f"- {subject}的{attribute}：{value}"
        description = str(getattr(fact, "description", "") or "").strip()
        if description:
            line += f"（{compact_text(description, 120, keep='head')}）"
        chapter = getattr(fact, "chapter_established", None)
        if chapter is not None:
            line += f" [第{chapter}章确立]"
        lines.append(line)

    for event in reversed(list(events)):
        title = str(getattr(event, "title", "")).strip()
        description = str(getattr(event, "description", "")).strip()
        if not title and not description:
            continue
        story_day = getattr(event, "story_day", None)
        chapter = getattr(event, "chapter", None)
        position = []
        if story_day is not None:
            position.append(f"第{story_day}天")
        if chapter is not None:
            position.append(f"第{chapter}章")
        prefix = f"[{'/'.join(position)}] " if position else ""
        line = f"- 事件：{title}{prefix}：{description}"
        foreshadowing = str(getattr(event, "foreshadowing", "") or "").strip()
        if foreshadowing:
            line += f"（伏笔：{compact_text(foreshadowing, 120, keep='head')}）"
        lines.append(line)

    bounded = compact_text(
        "\n".join(lines),
        MAX_STORY_BIBLE_CONTEXT_CHARS,
        keep="both",
    )
    return [line for line in bounded.split("\n") if line.strip()]


def build_prompt_trace_summary(prompt: str) -> dict[str, object]:
    """生成可展示但不携带完整正文的工作流输入摘要。"""

    return {
        "prompt_length": len(prompt),
        "prompt_preview": compact_text(
            prompt,
            MAX_TRACE_PREVIEW_CHARS,
            keep="both",
        ),
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
    }


def build_review_content(content: str) -> str:
    """保留章节首尾，限制单个审核 Agent 的正文输入。"""

    return compact_text(content, MAX_REVIEW_CONTENT_CHARS, keep="both")


def build_previous_chapter_context(
    previous_chapters: Optional[Iterable[str]],
) -> List[str]:
    """限制前文章数、单章长度和前文总长度。"""

    if not previous_chapters:
        return []

    recent = list(previous_chapters)[-MAX_REVIEW_PREVIOUS_CHAPTERS:]
    newest_first: List[str] = []
    remaining = MAX_REVIEW_PREVIOUS_TOTAL_CHARS
    for chapter in reversed(recent):
        if remaining <= 0:
            break
        limit = min(MAX_REVIEW_PREVIOUS_CHAPTER_CHARS, remaining)
        bounded = compact_text(chapter, limit, keep="tail")
        if bounded.strip():
            newest_first.append(bounded)
            remaining -= len(bounded)
    return list(reversed(newest_first))
