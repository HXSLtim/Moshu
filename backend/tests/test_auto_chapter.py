"""自动章节的并发编号与后台投影回归测试。"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.routes import generation as generation_routes
from app.crud import novel as novel_crud
from app.models.schemas import AutoChapterRequest, ChapterNextCreate


def _patch_auto_chapter_context(monkeypatch, *, create_result=None, create_error=None):
    """配置不访问数据库和真实模型的自动章节上下文。"""
    novel = SimpleNamespace(
        id=1,
        user_id=7,
        title="并发长篇",
        genre="玄幻",
        worldview="世界观",
        description="故事简介",
    )
    base_chapter = SimpleNamespace(
        id=9,
        novel_id=1,
        chapter_number=5,
        title="旧参考章",
        content="参考正文",
    )
    chain = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content='{"title":"第101章","content":"模型生成正文"}'
            )
        )
    )

    class FakePrompt:
        def __or__(self, _llm):
            return chain

    monkeypatch.setattr(
        generation_routes.ChatPromptTemplate,
        "from_messages",
        MagicMock(return_value=FakePrompt()),
    )
    monkeypatch.setattr(generation_routes.novel_crud, "get_novel_by_id", MagicMock(return_value=novel))
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_chapter_by_id",
        MagicMock(return_value=base_chapter),
    )
    monkeypatch.setattr(
        generation_routes.novel_crud,
        "get_max_chapter_number",
        MagicMock(return_value=100),
    )
    create_mock = MagicMock()
    if create_error is not None:
        create_mock.side_effect = create_error
    else:
        create_mock.return_value = create_result
    monkeypatch.setattr(generation_routes.novel_crud, "create_next_chapter", create_mock)
    monkeypatch.setattr(
        generation_routes.rag_service,
        "prepare_chapter_projection",
        MagicMock(
            return_value={
                "_novel_lifecycle": "novel-lifecycle",
                "_owner_id": 7,
                "_source_lifecycle": "chapter-lifecycle",
            }
        ),
    )
    index_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(generation_routes.rag_service, "index_content", index_mock)
    return chain, create_mock, index_mock


@pytest.mark.asyncio
async def test_auto_chapter_reallocates_number_after_model_and_indexes_in_background(monkeypatch):
    """旧参考章不决定编号，模型结束后由服务端重算，RAG不阻塞响应。"""
    created = SimpleNamespace(
        id=22,
        novel_id=1,
        chapter_number=102,
        title="第102章",
        content="模型生成正文",
        word_count=len("模型生成正文"),
        version=1,
        created_at=datetime.now(),
        updated_at=None,
    )
    chain, create_mock, index_mock = _patch_auto_chapter_context(
        monkeypatch,
        create_result=created,
    )
    background_tasks = BackgroundTasks()

    result = await generation_routes.auto_create_chapter(
        request=AutoChapterRequest(
            novel_id=1,
            base_chapter_id=9,
            target_length=500,
        ),
        background_tasks=background_tasks,
        current_user=SimpleNamespace(id=7),
        db=object(),
    )

    assert chain.ainvoke.await_args.args[0]["target_chapter_number"] == 101
    assert result.chapter_number == 102
    chapter_input = create_mock.call_args.args[2]
    assert isinstance(chapter_input, ChapterNextCreate)
    assert chapter_input.title is None
    index_mock.assert_not_awaited()

    await background_tasks()
    index_mock.assert_awaited_once()
    metadata = index_mock.await_args.kwargs["metadata"]
    assert metadata == {
        "source": "chapter",
        "chapter_id": 22,
        "version": 1,
        "_novel_lifecycle": "novel-lifecycle",
        "_owner_id": 7,
        "_source_lifecycle": "chapter-lifecycle",
    }


@pytest.mark.asyncio
async def test_auto_chapter_maps_allocation_conflict_to_409(monkeypatch):
    """服务端有限重试仍冲突时，API返回可重试的409而不是500。"""
    _patch_auto_chapter_context(
        monkeypatch,
        create_error=novel_crud.ChapterNumberConflictError("并发冲突，请重试"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await generation_routes.auto_create_chapter(
            request=AutoChapterRequest(novel_id=1, base_chapter_id=9),
            background_tasks=BackgroundTasks(),
            current_user=SimpleNamespace(id=7),
            db=object(),
        )

    assert exc_info.value.status_code == 409
    assert "并发冲突" in exc_info.value.detail
