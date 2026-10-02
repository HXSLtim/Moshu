"""章节审核预算、并发和失败关闭测试。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.services.context.budget import (
    MAX_REVIEW_CONTENT_CHARS,
    MAX_REVIEW_PREVIOUS_TOTAL_CHARS,
)
from app.services.review.service import ReviewAgentService
from app.services.review.agents import (
    CharacterConsistencyPayload,
    ContentSafetyPayload,
    PaceReviewPayload,
    StyleReviewPayload,
    parse_json_response,
    review_content_safety_agent,
)


def _service():
    service = ReviewAgentService.__new__(ReviewAgentService)
    service.llm = object()
    service._semaphore = asyncio.Semaphore(2)
    return service


def _success_results():
    return {
        "pace": {"score": 80, "pace_type": "medium", "issues": [], "suggestions": [], "details": {}},
        "quality": {"score": 80, "grammar_score": 80, "logic_score": 80, "description_score": 80, "issues": [], "suggestions": []},
        "plot": {"score": 80, "coherence_issues": [], "plot_holes": [], "suggestions": []},
        "character": {"score": 80, "inconsistencies": [], "suggestions": []},
        "style": {"score": 80, "style_type": "现代", "consistency_score": 80, "issues": [], "suggestions": []},
        "safety": {"is_safe": True, "risk_level": "low", "flagged_content": [], "suggestions": []},
    }


@pytest.mark.asyncio
async def test_failed_safety_review_never_allows_publish():
    values = _success_results()
    patches = [
        patch("app.services.review.service.review_pace_agent", AsyncMock(return_value=values["pace"])),
        patch("app.services.review.service.review_quality_agent", AsyncMock(return_value=values["quality"])),
        patch("app.services.review.service.review_plot_coherence_agent", AsyncMock(return_value=values["plot"])),
        patch("app.services.review.service.review_character_consistency_agent", AsyncMock(return_value=values["character"])),
        patch("app.services.review.service.review_style_agent", AsyncMock(return_value=values["style"])),
        patch("app.services.review.service.review_content_safety_agent", AsyncMock(side_effect=RuntimeError("模型不可用"))),
    ]
    for item in patches:
        item.start()
    try:
        result = await _service().review_chapter_comprehensive(1, 1, 1, "正文")
    finally:
        for item in reversed(patches):
            item.stop()

    assert result["review_status"] == "partial"
    assert result["failed_agents"] == ["safety"]
    assert result["content_safety"]["is_safe"] is False
    assert result["is_ready_for_publish"] is False


@pytest.mark.asyncio
async def test_string_safety_boolean_is_validation_failure_and_fails_closed():
    """模型返回字符串false时，不能被Python真值规则误判为安全。"""
    values = _success_results()
    values["safety"] = {
        "is_safe": "false",
        "risk_level": "low",
        "flagged_content": [],
        "suggestions": [],
    }
    with (
        patch("app.services.review.service.review_pace_agent", AsyncMock(return_value=values["pace"])),
        patch("app.services.review.service.review_quality_agent", AsyncMock(return_value=values["quality"])),
        patch("app.services.review.service.review_plot_coherence_agent", AsyncMock(return_value=values["plot"])),
        patch("app.services.review.service.review_character_consistency_agent", AsyncMock(return_value=values["character"])),
        patch("app.services.review.service.review_style_agent", AsyncMock(return_value=values["style"])),
        patch("app.services.review.service.review_content_safety_agent", AsyncMock(return_value=values["safety"])),
    ):
        result = await _service().review_chapter_comprehensive(1, 1, 1, "正文")

    assert result["failed_agents"] == ["safety"]
    assert result["content_safety"]["is_safe"] is False
    assert result["is_ready_for_publish"] is False


@pytest.mark.asyncio
async def test_publish_flag_is_real_bool_and_only_literal_true_can_pass():
    values = _success_results()
    with (
        patch("app.services.review.service.review_pace_agent", AsyncMock(return_value=values["pace"])),
        patch("app.services.review.service.review_quality_agent", AsyncMock(return_value=values["quality"])),
        patch("app.services.review.service.review_plot_coherence_agent", AsyncMock(return_value=values["plot"])),
        patch("app.services.review.service.review_character_consistency_agent", AsyncMock(return_value=values["character"])),
        patch("app.services.review.service.review_style_agent", AsyncMock(return_value=values["style"])),
        patch("app.services.review.service.review_content_safety_agent", AsyncMock(return_value=values["safety"])),
    ):
        result = await _service().review_chapter_comprehensive(1, 1, 1, "正文")

    assert type(result["is_ready_for_publish"]) is bool
    assert result["is_ready_for_publish"] is True


@pytest.mark.parametrize(
    ("result_model", "payload"),
    [
        (
            PaceReviewPayload,
            {"score": 101, "pace_type": "medium", "issues": [], "suggestions": [], "details": {}},
        ),
        (
            PaceReviewPayload,
            {"score": 80, "pace_type": "unknown", "issues": [], "suggestions": [], "details": {}},
        ),
        (
            StyleReviewPayload,
            {"score": 80, "style_type": "现代", "consistency_score": -1, "issues": [], "suggestions": []},
        ),
        (
            CharacterConsistencyPayload,
            {
                "score": 80,
                "inconsistencies": [{"type": "其他", "description": "类型不在契约内"}],
                "suggestions": [],
            },
        ),
        (
            ContentSafetyPayload,
            {"is_safe": True, "risk_level": "unknown", "flagged_content": [], "suggestions": []},
        ),
        (
            ContentSafetyPayload,
            {
                "is_safe": False,
                "risk_level": "high",
                "flagged_content": [{"type": "暴力", "description": "命中", "severity": "critical"}],
                "suggestions": [],
            },
        ),
    ],
)
def test_review_payload_contract_rejects_out_of_range_and_unknown_enums(
    result_model,
    payload,
):
    with pytest.raises(ValidationError):
        parse_json_response(json.dumps(payload, ensure_ascii=False), result_model)


@pytest.mark.asyncio
async def test_review_context_is_bounded_before_agents_run():
    values = _success_results()
    pace = AsyncMock(return_value=values["pace"])
    plot_agent = AsyncMock(return_value=values["plot"])
    with (
        patch("app.services.review.service.review_pace_agent", pace),
        patch("app.services.review.service.review_quality_agent", AsyncMock(return_value=values["quality"])),
        patch("app.services.review.service.review_plot_coherence_agent", plot_agent),
        patch("app.services.review.service.review_character_consistency_agent", AsyncMock(return_value=values["character"])),
        patch("app.services.review.service.review_style_agent", AsyncMock(return_value=values["style"])),
        patch("app.services.review.service.review_content_safety_agent", AsyncMock(return_value=values["safety"])),
    ):
        await _service().review_chapter_comprehensive(
            1,
            1,
            1,
            "正文" * 20_000,
            ["前文" * 5_000 for _ in range(5)],
        )

    assert len(pace.await_args.args[3]) <= MAX_REVIEW_CONTENT_CHARS
    previous = plot_agent.await_args.args[4]
    assert len(previous) <= 3
    assert sum(len(item) for item in previous) <= MAX_REVIEW_PREVIOUS_TOTAL_CHARS


@pytest.mark.asyncio
async def test_review_concurrency_is_limited_to_two():
    service = _service()
    active = 0
    maximum = 0

    async def worker():
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1

    await asyncio.gather(*(service._run_limited(worker()) for _ in range(6)))

    assert maximum == 2


@pytest.mark.asyncio
async def test_safety_agent_propagates_model_failure():
    chain = AsyncMock()
    chain.ainvoke.side_effect = RuntimeError("审核模型故障")
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain

    with patch(
        "app.services.review.agents.ChatPromptTemplate.from_messages",
        return_value=prompt_template,
    ):
        with pytest.raises(RuntimeError, match="审核模型故障"):
            await review_content_safety_agent(
                object(),
                novel_id=1,
                chapter_number=1,
                content="正文",
                workflow_steps=[],
            )
