"""Story Bible 事实账本与剧情事件的 CRUD、预算与租户隔离回归测试。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.api.dependencies import get_current_user
from app.api.routes import story_bible as story_bible_routes
from app.crud.novel import delete_novel
from app.db.base import Base, get_db
from app.models.novel import Novel
from app.models.story_bible import StoryEvent, StoryFact
from app.models.story_bible_schemas import (
    EventCreate,
    EventUpdate,
    FactCreate,
    FactUpdate,
)
from app.models.user import User


@pytest.fixture
def story_bible_api():
    """创建独立内存数据库与 Story Bible 路由测试客户端。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    setup_db = testing_session()
    setup_db.add_all(
        [
            User(id=1, username="owner", email="owner@example.com", hashed_password="x"),
            User(
                id=2,
                username="intruder",
                email="intruder@example.com",
                hashed_password="x",
            ),
        ]
    )
    setup_db.commit()
    setup_db.add_all(
        [
            Novel(id=1, title="他人小说", user_id=1),
            Novel(id=2, title="当前用户小说", user_id=2),
        ]
    )
    setup_db.commit()
    current_user = setup_db.get(User, 2)

    app = FastAPI()
    app.include_router(story_bible_routes.router, prefix="/api/story-bible")

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    async def override_user():
        return current_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    yield TestClient(app, raise_server_exceptions=False), setup_db

    setup_db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _create_fact(client: TestClient, **overrides):
    """通过 API 创建属于当前用户小说的测试事实。"""
    payload = {
        "novel_id": 2,
        "subject": "林夏",
        "attribute": "位置",
        "value": "青州城",
    }
    payload.update(overrides)
    return client.post("/api/story-bible/facts", json=payload)


def test_public_fact_creation_binds_current_novel_lifecycle(story_bible_api):
    """公开事实写入不能只保存可复用的整数小说 ID。"""
    client, db = story_bible_api
    response = _create_fact(client)
    assert response.status_code == 201
    fact = db.query(StoryFact).filter_by(id=response.json()["id"]).one()
    assert fact.novel_lifecycle_id == db.get(Novel, 2).rag_lifecycle_id


def test_deleted_novel_ledger_cannot_leak_through_reused_id(story_bible_api):
    """删除作品清理全部账本，其他作者复用小说主键时不能读到旧设定。"""
    client, db = story_bible_api
    db.add_all([
        StoryFact(novel_id=1, subject="旧人物", attribute="身份", value="保密设定"),
        StoryFact(novel_id=1, subject="旧人物", attribute="位置", value="旧城", status="retired"),
        StoryEvent(novel_id=1, title="旧计划", description="保密剧情", status="planned"),
        StoryEvent(novel_id=1, title="旧事件", description="已发生剧情", status="occurred"),
        StoryFact(novel_id=2, subject="当前人物", attribute="身份", value="应保留"),
        StoryEvent(novel_id=2, title="当前事件", description="应保留"),
    ])
    db.commit()

    assert delete_novel(db, 1)
    assert db.query(StoryFact).filter_by(novel_id=1).count() == 0
    assert db.query(StoryEvent).filter_by(novel_id=1).count() == 0
    assert db.query(StoryFact).filter_by(novel_id=2).count() == 1
    assert db.query(StoryEvent).filter_by(novel_id=2).count() == 1

    # 显式复用旧 ID，验证隔离不依赖数据库当前的分配顺序。
    db.add(Novel(id=1, title="当前作者的新作品", user_id=2))
    db.commit()
    for resource in ("facts", "events"):
        response = client.get(f"/api/story-bible/{resource}", params={"novel_id": 1})
        assert response.status_code == 200
        assert response.json() == []


def _create_event(client: TestClient, **overrides):
    """通过 API 创建属于当前用户小说的测试事件。"""
    payload = {
        "novel_id": 2,
        "title": "初入青州",
        "description": "主角进入青州城，发现城门戒严。",
    }
    payload.update(overrides)
    return client.post("/api/story-bible/events", json=payload)


def test_fact_crud_flow_preserves_retired_history(story_bible_api):
    """事实从创建到退役保持可查询，退役时默认沿用确立章节。"""
    client, db = story_bible_api

    created = _create_fact(client, chapter_established=3, description="第一卷主线")
    assert created.status_code == 201
    fact = created.json()
    assert fact["novel_id"] == 2
    assert fact["status"] == "active"
    assert fact["retired_chapter"] is None

    listed = client.get(
        "/api/story-bible/facts",
        params={"novel_id": 2, "status_filter": "active", "skip": 0, "limit": 100},
    )
    assert listed.status_code == 200
    assert listed.json() == [fact]

    detail = client.get(f"/api/story-bible/facts/{fact['id']}")
    assert detail.status_code == 200
    assert detail.json() == fact

    updated = client.put(
        f"/api/story-bible/facts/{fact['id']}",
        json={"status": "retired", "value": "云梦泽"},
    )
    assert updated.status_code == 200
    assert updated.json()["value"] == "云梦泽"
    assert updated.json()["status"] == "retired"
    # 未指定失效章节时，服务端默认沿用确立章节，保证账本可追溯。
    assert updated.json()["retired_chapter"] == 3

    active = client.get(
        "/api/story-bible/facts",
        params={"novel_id": 2, "status_filter": "active"},
    )
    retired = client.get(
        "/api/story-bible/facts",
        params={"novel_id": 2, "status_filter": "retired"},
    )
    assert active.status_code == 200
    assert active.json() == []
    assert retired.status_code == 200
    assert [item["id"] for item in retired.json()] == [fact["id"]]

    deleted = client.delete(f"/api/story-bible/facts/{fact['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/story-bible/facts/{fact['id']}").status_code == 404
    db.expire_all()
    assert db.query(StoryFact).filter_by(id=fact["id"]).count() == 0


def test_fact_writes_reject_empty_unknown_and_oversized_input(story_bible_api):
    """事实写入在进入 CRUD 前拒绝空更新、未知字段和超预算文本。"""
    client, _ = story_bible_api

    empty_update = client.put("/api/story-bible/facts/1", json={})
    unknown_create = _create_fact(client, unknown_field=True)
    oversized_value = _create_fact(client, value="x" * 2001)
    invalid_status = client.get(
        "/api/story-bible/facts",
        params={"novel_id": 2, "status_filter": "deleted"},
    )

    assert empty_update.status_code == 422
    assert unknown_create.status_code == 422
    assert oversized_value.status_code == 422
    assert invalid_status.status_code == 422


def test_event_crud_flow_orders_by_story_day(story_bible_api):
    """事件按故事天数排序，可更新状态并删除。"""
    client, db = story_bible_api

    first = _create_event(client, story_day=2)
    second = _create_event(client, title="离开青州", story_day=1)
    assert first.status_code == 201
    assert second.status_code == 201
    first_event = first.json()
    second_event = second.json()
    assert second_event["status"] == "planned"

    listed = client.get("/api/story-bible/events", params={"novel_id": 2})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [second_event["id"], first_event["id"]]

    updated = client.put(
        f"/api/story-bible/events/{second_event['id']}",
        json={"status": "occurred", "foreshadowing": "城卫认得主角的玉佩"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "occurred"
    assert updated.json()["foreshadowing"] == "城卫认得主角的玉佩"

    deleted = client.delete(f"/api/story-bible/events/{first_event['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/story-bible/events/{first_event['id']}").status_code == 404
    db.expire_all()
    assert db.query(StoryEvent).filter_by(id=first_event["id"]).count() == 0


def test_event_schema_budgets_reject_unbounded_character_lists_and_bad_status():
    """剧情事件的角色名单数量、单项长度与状态枚举都有写入预算。"""
    with pytest.raises(ValidationError):
        EventCreate(novel_id=1, title="事件", description="正文", status="happened")

    with pytest.raises(ValidationError):
        EventCreate(
            novel_id=1,
            title="事件",
            description="正文",
            involved_characters=["角色"] * 51,
        )

    with pytest.raises(ValidationError):
        EventCreate(
            novel_id=1,
            title="事件",
            description="正文",
            involved_characters=["x" * 101],
        )

    with pytest.raises(ValidationError):
        EventUpdate()

    with pytest.raises(ValidationError):
        FactCreate(novel_id=1, subject="", attribute="位置", value="青州")

    with pytest.raises(ValidationError):
        FactUpdate(value=None, description=None, chapter_established=None)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/story-bible/facts?novel_id=1"),
        ("POST", "/api/story-bible/facts"),
        ("GET", "/api/story-bible/facts/1"),
        ("PUT", "/api/story-bible/facts/1"),
        ("DELETE", "/api/story-bible/facts/1"),
        ("GET", "/api/story-bible/events?novel_id=1"),
        ("POST", "/api/story-bible/events"),
        ("GET", "/api/story-bible/events/1"),
        ("PUT", "/api/story-bible/events/1"),
        ("DELETE", "/api/story-bible/events/1"),
    ],
)
def test_foreign_novel_resources_return_404_for_facts_and_events(
    story_bible_api,
    method,
    path,
):
    """小说归属错误或资源属于他人小说时，统一返回 404 不泄漏存在性。"""
    client, db = story_bible_api

    db.add_all(
        [
            StoryFact(
                id=1,
                novel_id=1,
                subject="他人事实",
                attribute="位置",
                value="他城",
                status="active",
            ),
            StoryEvent(
                id=1,
                novel_id=1,
                title="他人事件",
                description="只属于他人小说",
                story_day=1,
                status="planned",
            ),
        ]
    )
    db.commit()

    if method == "POST":
        response = client.post(
            path,
            json={"novel_id": 1, "subject": "越权", "attribute": "位置", "value": "青州"}
            if "facts" in path
            else {"novel_id": 1, "title": "越权事件", "description": "正文"},
        )
    elif method == "PUT":
        response = client.put(
            path,
            json={"value": "越权更新"}
            if "facts" in path
            else {"title": "越权更新"},
        )
    else:
        response = client.request(method, path)

    assert response.status_code == 404
