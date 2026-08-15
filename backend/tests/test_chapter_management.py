"""章节契约、分页和并发保存的回归测试。"""

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.api.dependencies import get_current_user
from app.api.routes import novels as novel_routes
from app.crud import novel as novel_crud
from app.db.base import Base, get_db
from app.models.novel import Novel
from app.models.schemas import ChapterCreate, ChapterUpdate, GenerationRequest, RAGQuery
from app.models.user import User


@pytest.fixture
def chapter_api(monkeypatch):
    """创建使用独立内存数据库的小说路由测试客户端。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    user = User(
        username="chapter-owner",
        email="chapter-owner@example.com",
        hashed_password="not-used",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    novel = Novel(title="长篇测试", user_id=user.id)
    db.add(novel)
    db.commit()
    db.refresh(novel)

    app = FastAPI()
    app.include_router(novel_routes.router, prefix="/api/novels")

    def override_db():
        request_db = testing_session()
        try:
            yield request_db
        finally:
            request_db.close()

    async def override_user():
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    monkeypatch.setattr(
        novel_routes.rag_service,
        "index_content",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        novel_routes.rag_service,
        "cleanup_chapter_data",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        novel_routes.rag_service,
        "cleanup_novel_vectors",
        AsyncMock(return_value=0),
    )

    yield TestClient(app), db, novel

    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _create_chapter(db, novel_id: int, chapter_number: int):
    return novel_crud.create_chapter(
        db,
        novel_id,
        ChapterCreate(
            chapter_number=chapter_number,
            title=f"第{chapter_number}章",
            content=f"正文{chapter_number}",
        ),
    )


def test_chapter_summary_pagination_and_server_next(chapter_api):
    """超过100章时摘要分页完整，下一章编号由服务端正确分配。"""
    client, db, novel = chapter_api
    chapters = [_create_chapter(db, novel.id, number) for number in range(1, 121)]

    response = client.get(
        f"/api/novels/{novel.id}/chapters",
        params={"page": 3, "page_size": 50},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 120
    assert data["has_more"] is False
    assert [item["chapter_number"] for item in data["items"]] == list(range(101, 121))
    assert all("content" not in item for item in data["items"])
    assert all(item["version"] == 1 for item in data["items"])

    detail = client.get(f"/api/novels/{novel.id}/chapters/{chapters[118].id}")
    assert detail.status_code == 200
    assert detail.json()["chapter_number"] == 119
    assert detail.json()["content"] == "正文119"

    created = client.post(
        f"/api/novels/{novel.id}/chapters/next",
        json={"content": "服务端分配章节号"},
    )
    assert created.status_code == 201
    assert created.json()["chapter_number"] == 121
    assert created.json()["version"] == 1


def test_novel_statistics_use_one_aggregate_query_and_isolate_user(chapter_api):
    """固定统计路由用一次查询覆盖零章节小说，并隔离其他用户数据。"""
    client, db, novel = chapter_api
    _create_chapter(db, novel.id, 1)
    _create_chapter(db, novel.id, 2)

    empty_novel = Novel(title="零章节小说", user_id=novel.user_id)
    other_user = User(
        username="statistics-other",
        email="statistics-other@example.com",
        hashed_password="not-used",
    )
    db.add_all([empty_novel, other_user])
    db.commit()
    db.refresh(empty_novel)
    db.refresh(other_user)

    other_novel = Novel(title="他人小说", user_id=other_user.id)
    db.add(other_novel)
    db.commit()
    db.refresh(other_novel)
    _create_chapter(db, other_novel.id, 1)

    # 最后一次提交会让同一会话中的认证用户过期，先加载其主键以免干扰SQL计数。
    owner = db.get(User, novel.user_id)
    assert owner is not None
    _ = owner.id

    executed_selects: list[str] = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            executed_selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record_select)
    try:
        response = client.get("/api/novels/statistics")
    finally:
        event.remove(engine, "before_cursor_execute", record_select)

    assert response.status_code == 200
    stats = {item["novel_id"]: item for item in response.json()["items"]}
    assert stats[novel.id] == {
        "novel_id": novel.id,
        "chapter_count": 2,
        "total_words": len("正文1") + len("正文2"),
    }
    assert stats[empty_novel.id] == {
        "novel_id": empty_novel.id,
        "chapter_count": 0,
        "total_words": 0,
    }
    assert other_novel.id not in stats
    assert len(executed_selects) == 1


def test_novel_worldview_is_indexed_on_create_and_update_with_persisted_version(
    chapter_api,
    monkeypatch,
):
    """携带世界观的新建和更新都排队索引，版本由数据库原子递增。"""
    client, db, novel = chapter_api
    index_mock = novel_routes.rag_service.index_content
    index_mock.reset_mock()
    prepare_novel = MagicMock(
        return_value={"_novel_lifecycle": "novel-lifecycle", "_owner_id": novel.user_id}
    )
    prepare_worldview = MagicMock(
        side_effect=[
            {
                "_novel_lifecycle": "novel-lifecycle",
                "_owner_id": novel.user_id,
                "_source_lifecycle": "novel-lifecycle",
            },
            {
                "_novel_lifecycle": "novel-lifecycle",
                "_owner_id": novel.user_id,
                "_source_lifecycle": "novel-lifecycle",
            },
        ]
    )
    monkeypatch.setattr(novel_routes.rag_service, "prepare_novel_projection", prepare_novel)
    monkeypatch.setattr(
        novel_routes.rag_service,
        "prepare_worldview_projection",
        prepare_worldview,
    )

    created_response = client.post(
        "/api/novels/",
        json={"title": "带世界观的新书", "worldview": "初始世界观"},
    )
    assert created_response.status_code == 201
    created = novel_crud.get_novel_by_id(db, created_response.json()["id"])
    first_metadata = index_mock.await_args_list[0].kwargs["metadata"]
    assert first_metadata["version"] == novel_routes._worldview_projection_version(created)
    assert first_metadata["_novel_lifecycle"] == "novel-lifecycle"
    assert first_metadata["_source_lifecycle"] == "novel-lifecycle"
    prepare_novel.assert_called_once_with(created.id, db=ANY)
    assert prepare_novel.call_args.kwargs["db"].get_bind() == db.get_bind()

    updated_response = client.put(
        f"/api/novels/{created.id}",
        json={"worldview": "更新后的世界观"},
    )
    assert updated_response.status_code == 200
    db.refresh(created)
    second_metadata = index_mock.await_args_list[1].kwargs["metadata"]
    assert second_metadata["version"] == novel_routes._worldview_projection_version(created)
    assert second_metadata["version"] == first_metadata["version"] + 1
    assert second_metadata["_novel_lifecycle"] == "novel-lifecycle"
    assert index_mock.await_count == 2


def test_chapter_update_prepares_persistent_projection_identity(chapter_api, monkeypatch):
    """普通章节更新携带数据库持久生命周期，而不是进程内代次。"""
    client, db, novel = chapter_api
    chapter = _create_chapter(db, novel.id, 1)
    prepare = MagicMock(
        return_value={
            "_novel_lifecycle": "novel-lifecycle",
            "_owner_id": novel.user_id,
            "_source_lifecycle": "chapter-lifecycle",
        }
    )
    monkeypatch.setattr(novel_routes.rag_service, "prepare_chapter_projection", prepare)
    index_mock = novel_routes.rag_service.index_content
    index_mock.reset_mock()

    response = client.put(
        f"/api/novels/{novel.id}/chapters/{chapter.id}",
        json={"expected_version": 1, "content": "更新正文"},
    )

    assert response.status_code == 200
    prepare.assert_called_once_with(novel.id, chapter.id, db=ANY)
    assert prepare.call_args.kwargs["db"].get_bind() == db.get_bind()
    metadata = index_mock.await_args.kwargs["metadata"]
    assert metadata["_novel_lifecycle"] == "novel-lifecycle"
    assert metadata["_source_lifecycle"] == "chapter-lifecycle"


def test_chapter_update_uses_version_and_rejects_unknown_fields(chapter_api):
    """更新真实修改章节号，并阻止空更新、未知字段和迟到旧版本覆盖。"""
    client, db, novel = chapter_api
    chapter = _create_chapter(db, novel.id, 1)

    empty_chapter_update = client.put(
        f"/api/novels/{novel.id}/chapters/{chapter.id}",
        json={"expected_version": 1},
    )
    assert empty_chapter_update.status_code == 422

    empty_novel_update = client.put(f"/api/novels/{novel.id}", json={})
    assert empty_novel_update.status_code == 422

    unknown = client.put(
        f"/api/novels/{novel.id}/chapters/{chapter.id}",
        json={"expected_version": 1, "title": "新标题", "unknown": True},
    )
    assert unknown.status_code == 422

    updated = client.put(
        f"/api/novels/{novel.id}/chapters/{chapter.id}",
        json={"expected_version": 1, "chapter_number": 2, "content": "新正文"},
    )
    assert updated.status_code == 200
    assert updated.json()["chapter_number"] == 2
    assert updated.json()["version"] == 2
    assert updated.json()["word_count"] == len("新正文")

    stale = client.put(
        f"/api/novels/{novel.id}/chapters/{chapter.id}",
        json={"expected_version": 1, "content": "迟到的旧正文"},
    )
    assert stale.status_code == 409

    detail = client.get(f"/api/novels/{novel.id}/chapters/{chapter.id}")
    assert detail.json()["content"] == "新正文"
    assert detail.json()["version"] == 2


def test_chapter_number_conflicts_are_409(chapter_api):
    """显式创建和重编号都由数据库唯一约束兜底并统一返回409。"""
    client, db, novel = chapter_api
    first = _create_chapter(db, novel.id, 1)
    _create_chapter(db, novel.id, 2)

    duplicate = client.post(
        f"/api/novels/{novel.id}/chapters",
        json={"chapter_number": 2, "title": "重复章节", "content": ""},
    )
    assert duplicate.status_code == 409

    renumber = client.put(
        f"/api/novels/{novel.id}/chapters/{first.id}",
        json={"expected_version": 1, "chapter_number": 2},
    )
    assert renumber.status_code == 409


def test_crud_optimistic_update_is_atomic(chapter_api):
    """CRUD层对同一旧版本只允许一次更新成功。"""
    _, db, novel = chapter_api
    chapter = _create_chapter(db, novel.id, 1)

    result = novel_crud.update_chapter(
        db,
        chapter.id,
        ChapterUpdate(expected_version=1, content="第一次更新"),
    )
    assert result.version == 2

    with pytest.raises(novel_crud.ChapterVersionConflictError) as exc_info:
        novel_crud.update_chapter(
            db,
            chapter.id,
            ChapterUpdate(expected_version=1, content="第二次旧更新"),
        )
    assert exc_info.value.current_version == 2


def test_chapter_word_count_uses_unified_text_stats(chapter_api):
    """章节创建与更新按统一规则排除空白，并忽略组合标记。"""
    client, _, novel = chapter_api

    created = client.post(
        f"/api/novels/{novel.id}/chapters",
        json={"chapter_number": 1, "title": "字数测试", "content": "  你好\n世界  "},
    )
    assert created.status_code == 201
    assert created.json()["word_count"] == 4

    updated = client.put(
        f"/api/novels/{novel.id}/chapters/{created.json()['id']}",
        json={"expected_version": 1, "content": "e\u0301"},
    )
    assert updated.status_code == 200
    assert updated.json()["word_count"] == 1


def test_generation_and_rag_requests_have_hard_bounds():
    """过大的模型上下文和召回数量在进入服务前即被拒绝。"""
    with pytest.raises(ValueError):
        GenerationRequest(novel_id=1, prompt="x" * 4001, chapter=1)
    with pytest.raises(ValueError):
        GenerationRequest(novel_id=1, prompt="正常", chapter=1, target_length=8001)
    with pytest.raises(ValueError):
        RAGQuery(novel_id=1, query="设定", top_k=21)
