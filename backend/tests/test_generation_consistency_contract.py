"""续写接口的一致性终态透传契约测试。"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes import generation as generation_routes
from app.models.schemas import (
    AgentOutput,
    AgentType,
    ConsistencyCheckResult,
    ConsistencyCheckType,
    FinalConsistencyStatus,
    GenerationResponse,
)


def _conflicted_response() -> GenerationResponse:
    return GenerationResponse(
        novel_id=1,
        chapter=3,
        final_content="冲突稿",
        agent_outputs=[AgentOutput(agent_type=AgentType.PLOT, content="冲突稿")],
        consistency_checks=[
            ConsistencyCheckResult(
                check_type=ConsistencyCheckType.TIMELINE,
                is_valid=False,
                violations=["时间线冲突"],
            )
        ],
        retry_count=2,
        final_consistency=FinalConsistencyStatus(
            status="conflict_after_retries",
            has_conflict=True,
            retry_exhausted=True,
            is_complete=False,
            checks_skipped=["knowledge_graph"],
            violations=["时间线冲突"],
        ),
        generated_at=datetime.now(),
    )


def _patch_owned_chapter(monkeypatch):
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_novel_by_id",
        MagicMock(
            return_value=SimpleNamespace(
                id=1,
                user_id=7,
                title="续写测试",
                genre="玄幻",
                worldview="世界观",
            )
        ),
    )
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_chapter_by_id",
        MagicMock(return_value=SimpleNamespace(id=3, novel_id=1, chapter_number=3)),
    )


@pytest.mark.asyncio
async def test_continue_returns_final_consistency(monkeypatch):
    """非流式续写返回检查列表、重试次数和最终冲突状态。"""
    _patch_owned_chapter(monkeypatch)
    monkeypatch.setattr(
        generation_routes.agent_service,
        "generate_content",
        AsyncMock(return_value=_conflicted_response()),
    )

    result = await generation_routes.continue_chapter(
        request=generation_routes.ContinueRequest(
            novel_id=1,
            chapter_id=3,
            current_content="已有正文",
            use_rag_style=False,
        ),
        current_user=SimpleNamespace(id=7),
        db=object(),
    )

    assert result["retry_count"] == 2
    assert result["consistency_checks"][0]["is_valid"] is False
    assert result["final_consistency"] == {
        "status": "conflict_after_retries",
        "has_conflict": True,
        "retry_exhausted": True,
        "is_complete": False,
        "checks_skipped": ["knowledge_graph"],
        "violations": ["时间线冲突"],
    }


@pytest.mark.asyncio
async def test_continue_stream_metadata_returns_final_consistency(monkeypatch):
    """流式续写在正文前的metadata中暴露相同终态。"""
    _patch_owned_chapter(monkeypatch)

    async def fake_stream(_request):
        yield {"type": "final_response", "data": _conflicted_response()}

    monkeypatch.setattr(
        generation_routes.agent_service,
        "generate_content_stream",
        fake_stream,
    )
    http_request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    response = await generation_routes.continue_chapter_stream(
        request=generation_routes.ContinueRequest(
            novel_id=1,
            chapter_id=3,
            current_content="已有正文",
            use_rag_style=False,
        ),
        http_request=http_request,
        current_user=SimpleNamespace(id=7),
        db=object(),
    )
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in "".join(chunks).splitlines()
        if line.startswith("data: ")
    ]

    metadata = payloads[0]["data"]
    assert payloads[0]["type"] == "metadata"
    assert metadata["retry_count"] == 2
    assert metadata["final_consistency"]["status"] == "conflict_after_retries"
    assert metadata["final_consistency"]["is_complete"] is False
    assert metadata["final_consistency"]["checks_skipped"] == ["knowledge_graph"]
    assert metadata["final_consistency"]["violations"] == ["时间线冲突"]
