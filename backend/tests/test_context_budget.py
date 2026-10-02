"""AI 上下文预算单元测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.context.budget import (
    MAX_GENERATION_PROMPT_CHARS,
    MAX_REVIEW_PREVIOUS_TOTAL_CHARS,
    MAX_STORY_CONTEXT_CHARS,
    MAX_WORLDVIEW_CONTEXT_CHARS,
    build_previous_chapter_context,
    build_prompt_trace_summary,
    compact_text,
    ensure_generation_prompt_budget,
)
from app.services.generation.creative_tools import analyze_character, generate_character


def test_compact_text_keeps_head_and_tail_within_budget():
    text = "开" * 100 + "结" * 100

    result = compact_text(text, 80, keep="both")

    assert len(result) == 80
    assert result.startswith("开")
    assert result.endswith("结")


def test_generation_prompt_over_budget_is_rejected():
    with pytest.raises(ValueError, match="不能超过"):
        ensure_generation_prompt_budget("字" * (MAX_GENERATION_PROMPT_CHARS + 1))


def test_trace_summary_does_not_contain_full_prompt():
    prompt = "开头" + "敏感正文" * 200 + "结尾"

    summary = build_prompt_trace_summary(prompt)

    assert summary["prompt_length"] == len(prompt)
    assert summary["prompt_preview"] != prompt
    assert len(summary["prompt_hash"]) == 16


def test_previous_chapter_context_has_count_and_total_budget():
    chapters = [f"第{i}章" + str(i) * 4000 for i in range(5)]

    result = build_previous_chapter_context(chapters)

    assert len(result) <= 3
    assert sum(len(item) for item in result) <= MAX_REVIEW_PREVIOUS_TOTAL_CHARS
    assert result[-1].endswith("4" * 100)


@pytest.mark.asyncio
async def test_character_generation_compacts_persisted_and_nested_context():
    """角色生成不能把完整世界观、要求和全部角色名原样发送给模型。"""

    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content='{"name":"测试角色"}')
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain
    context = {
        "novel_title": "测试小说",
        "novel_genre": "玄幻",
        "worldview": "世界" * 30_000,
        "character_requirements": "要求" * 10_000,
        "existing_characters": [f"角色{i}-" + "名" * 100 for i in range(500)],
    }

    with (
        patch(
            "app.services.generation.creative_tools.ChatPromptTemplate.from_template",
            return_value=prompt_template,
        ),
        patch("app.services.generation.creative_tools.create_chat_model", return_value=object()),
    ):
        await generate_character(context)

    model_context = chain.ainvoke.await_args.args[0]
    assert len(model_context["worldview"]) <= MAX_WORLDVIEW_CONTEXT_CHARS
    assert len(model_context["character_requirements"]) <= MAX_STORY_CONTEXT_CHARS
    assert len(str(model_context["existing_characters"])) <= MAX_STORY_CONTEXT_CHARS


@pytest.mark.asyncio
async def test_character_analysis_compacts_records_before_model_call():
    """关系和出场记录数量增长时，角色分析提示仍必须保持固定上限。"""

    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content="{}")
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain
    context = {
        "character": {
            "name": "主角",
            "age": 20,
            "personality": "性格" * 5_000,
            "background": "背景" * 5_000,
            "character_arc": "弧线" * 5_000,
        },
        "relationships": [
            {"target": f"角色{i}", "type": "朋友", "strength": 5}
            for i in range(2_000)
        ],
        "appearances": [
            {"chapter": i + 1, "type": "main", "importance": 5}
            for i in range(2_000)
        ],
        "analysis_type": "comprehensive",
    }

    with (
        patch(
            "app.services.generation.creative_tools.ChatPromptTemplate.from_template",
            return_value=prompt_template,
        ),
        patch("app.services.generation.creative_tools.create_chat_model", return_value=object()),
    ):
        await analyze_character(context)

    model_context = chain.ainvoke.await_args.args[0]
    assert len(model_context["personality"]) <= MAX_STORY_CONTEXT_CHARS
    assert len(model_context["background"]) <= MAX_STORY_CONTEXT_CHARS
    assert len(model_context["character_arc"]) <= MAX_STORY_CONTEXT_CHARS
    assert len(model_context["relationships"]) <= MAX_STORY_CONTEXT_CHARS
    assert len(model_context["appearances"]) <= MAX_STORY_CONTEXT_CHARS
