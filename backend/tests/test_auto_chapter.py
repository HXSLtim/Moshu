"""自动新章先成为候选；编号分配只发生于作者确认事务。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.routes import generation as routes
from app.models.schemas import AutoChapterRequest
from app.services.writing_tasks import TaskResult


@pytest.mark.asyncio
async def test_auto_chapter_only_persists_proposal_without_creating_or_indexing(monkeypatch):
    """生成返回候选，不建立章节、不启动临时后台索引。"""
    novel = SimpleNamespace(id=1, user_id=7, rag_lifecycle_id='a' * 32)
    base = SimpleNamespace(id=9, novel_id=1, version=1, rag_lifecycle_id='b' * 32, content='参考正文')
    monkeypatch.setattr(routes.novel_crud, 'get_novel_by_id', MagicMock(return_value=novel))
    monkeypatch.setattr(routes.novel_crud, 'get_chapter_by_id', MagicMock(return_value=base))
    monkeypatch.setattr(routes.novel_crud, 'get_max_chapter_number', MagicMock(return_value=100))
    task = AsyncMock(return_value=(TaskResult('候选正文', {'title': '候选标题'}), SimpleNamespace(manifest={}), {}))
    monkeypatch.setattr(routes, '_run_structured_task', task)
    proposal = SimpleNamespace(id='proposal-id', operation='create', status='pending')
    create = MagicMock(return_value=proposal)
    monkeypatch.setattr(routes, 'create_proposal', create)
    write = MagicMock(); index = AsyncMock()
    monkeypatch.setattr(routes.novel_crud, 'create_next_chapter', write)
    monkeypatch.setattr(routes.rag_service, 'index_content', index)
    background = BackgroundTasks()
    result = await routes.auto_create_chapter.__wrapped__(AutoChapterRequest(novel_id=1, base_chapter_id=9), background, SimpleNamespace(id=7), MagicMock())
    assert result is proposal
    assert task.await_args.kwargs['target_chapter'] == 101
    assert create.call_args.kwargs['base_content'] == '参考正文'
    write.assert_not_called(); index.assert_not_called()
    assert not background.tasks


@pytest.mark.asyncio
async def test_auto_chapter_rejects_changed_client_scope_before_model(monkeypatch):
    """旧页面的作品身份不能生成绑定新生命周期的候选。"""
    monkeypatch.setattr(routes.novel_crud, 'get_novel_by_id', MagicMock(return_value=SimpleNamespace(id=1, user_id=7, rag_lifecycle_id='a' * 32)))
    monkeypatch.setattr(routes.novel_crud, 'get_latest_chapter', MagicMock(return_value=None))
    task = AsyncMock(); monkeypatch.setattr(routes, '_run_structured_task', task)
    with pytest.raises(HTTPException) as exc:
        await routes.auto_create_chapter.__wrapped__(AutoChapterRequest(novel_id=1, expected_novel_lifecycle_id='b' * 32), BackgroundTasks(), SimpleNamespace(id=7), MagicMock())
    assert exc.value.status_code == 409
    task.assert_not_awaited()
