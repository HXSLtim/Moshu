"""续写接口的一致性终态透传契约测试。"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes import generation as generation_routes
from app.models.schemas import (
    StageOutput,
    StageType,
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
        stage_outputs=[StageOutput(agent_type=StageType.PLOT, content="冲突稿")],
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
        context_manifest={"version": 1, "sources": [], "fingerprint": "context-test"},
    )


def _patch_owned_chapter(monkeypatch):
    monkeypatch.setattr(generation_routes, "create_proposal", MagicMock(return_value=SimpleNamespace(id="proposal-id")))
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_novel_by_id",
        MagicMock(
            return_value=SimpleNamespace(
                id=1,
                user_id=7,
                rag_lifecycle_id="owned-life",
                title="续写测试",
                genre="玄幻",
                worldview="世界观",
            )
        ),
    )
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_chapter_by_id",
        MagicMock(return_value=SimpleNamespace(id=3, novel_id=1, chapter_number=3, version=1, rag_lifecycle_id='chapter-life')),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("current_day", [None, 9])
async def test_continue_returns_final_consistency(monkeypatch, current_day):
    """非流式续写返回检查列表、重试次数和最终冲突状态。"""
    _patch_owned_chapter(monkeypatch)
    monkeypatch.setattr(
        generation_routes.generation_workflow,
        "generate_content",
        AsyncMock(return_value=_conflicted_response()),
    )

    result = await generation_routes.continue_chapter.__wrapped__(
        request=generation_routes.ContinueRequest(
            novel_id=1,
            chapter_id=3,
            current_content="已有正文",
            use_rag_style=False,
            current_day=current_day,
        ),
        current_user=SimpleNamespace(id=7),
        db=MagicMock(),
    )

    assert generation_routes.generation_workflow.generate_content.await_args.args[0].current_day == current_day
    assert generation_routes.generation_workflow.generate_content.await_args.kwargs == {"actor_id": 7, "novel_lifecycle_id": "owned-life"}
    assert result["context_manifest"] == _conflicted_response().context_manifest
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
@pytest.mark.parametrize("current_day", [None, 9])
async def test_continue_stream_metadata_returns_final_consistency(monkeypatch, current_day):
    """流式续写在正文前的metadata中暴露相同终态。"""
    _patch_owned_chapter(monkeypatch)

    async def fake_stream(_request, *, actor_id, novel_lifecycle_id):
        assert (actor_id, novel_lifecycle_id) == (7, "owned-life")
        assert _request.current_day == current_day
        yield {"type": "final_response", "data": _conflicted_response()}

    monkeypatch.setattr(
        generation_routes.generation_workflow,
        "generate_content_stream",
        fake_stream,
    )
    http_request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    response = await generation_routes._continue_chapter_stream_impl(
        request=generation_routes.ContinueRequest(
            novel_id=1,
            chapter_id=3,
            current_content="已有正文",
            use_rag_style=False,
            current_day=current_day,
        ),
        http_request=http_request,
        current_user=SimpleNamespace(id=7),
        db=MagicMock(),
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
    assert metadata["context_manifest"] == _conflicted_response().context_manifest
    assert metadata["retry_count"] == 2
    assert metadata["final_consistency"]["status"] == "conflict_after_retries"
    assert metadata["final_consistency"]["is_complete"] is False
    assert metadata["final_consistency"]["checks_skipped"] == ["knowledge_graph"]
    assert metadata["final_consistency"]["violations"] == ["时间线冲突"]
