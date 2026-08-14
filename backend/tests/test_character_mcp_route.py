"""直连 Character MCP 的租户隔离与响应序列化回归测试。"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.api.dependencies import get_current_user
from app.api.routes import characters as character_routes
from app.db.base import Base, get_db
from app.models.character import Character, CharacterRelationship
from app.models.novel import Chapter, Novel
from app.models.user import User


@pytest.fixture
def character_mcp_api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    setup_db = testing_session()
    setup_db.add_all(
        [
            User(id=1, username="victim", email="victim@example.com", hashed_password="x"),
            User(id=2, username="operator", email="operator@example.com", hashed_password="x"),
            Novel(id=1, title="他人小说", user_id=1),
            Novel(id=2, title="当前用户小说", user_id=2),
        ]
    )
    setup_db.commit()
    setup_db.add_all(
        [
            Chapter(id=1, novel_id=1, chapter_number=1, title="第一章", content="正文"),
            Character(id=1, novel_id=1, name="他人角色甲"),
            Character(id=2, novel_id=1, name="他人角色乙"),
            Character(id=3, novel_id=2, name="当前用户角色甲"),
            Character(id=4, novel_id=2, name="当前用户角色乙"),
        ]
    )
    setup_db.commit()
    setup_db.add(
        CharacterRelationship(
            id=1,
            novel_id=1,
            character_a_id=1,
            character_b_id=2,
            relationship_type="enemy",
        )
    )
    setup_db.commit()
    current_user = setup_db.get(User, 2)

    app = FastAPI()
    app.include_router(character_routes.router, prefix="/api/characters")

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


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "create", "parameters": {"novel_id": 1, "name": "越权创建"}},
        {"action": "list", "parameters": {"novel_id": 1}},
        {"action": "search", "parameters": {"novel_id": 1, "search_term": "角色"}},
        {"action": "get_network", "parameters": {"novel_id": 1}},
        {"action": "generate_character", "parameters": {"novel_id": 1}},
        {"action": "update", "parameters": {"character_id": 1, "name": "越权更新"}},
        {"action": "delete", "parameters": {"character_id": 1}},
        {"action": "analyze", "parameters": {"character_id": 1}},
        {"action": "optimize", "parameters": {"character_id": 1}},
        {"action": "get", "parameters": {"character_id": 1}},
        {
            "action": "create_relationship",
            "parameters": {
                "novel_id": 1,
                "character_a_id": 1,
                "character_b_id": 2,
                "relationship_type": "friend",
            },
        },
        {"action": "update_relationship", "parameters": {"relationship_id": 1}},
        {
            "action": "track_appearance",
            "parameters": {"character_id": 1, "chapter_id": 1},
        },
        {
            "action": "batch_update",
            "parameters": {"updates": [{"character_id": 1, "data": {"name": "越权"}}]},
        },
    ],
)
def test_nested_targets_cannot_bypass_current_user_ownership(
    character_mcp_api,
    monkeypatch,
    payload,
):
    client, _ = character_mcp_api
    execute = AsyncMock()
    monkeypatch.setattr(character_routes.character_mcp_service, "execute_action", execute)

    response = client.post("/api/characters/mcp/execute", json=payload)

    assert response.status_code == 404
    execute.assert_not_awaited()


def test_top_level_and_nested_ids_must_resolve_to_one_novel(
    character_mcp_api,
    monkeypatch,
):
    client, _ = character_mcp_api
    execute = AsyncMock()
    monkeypatch.setattr(character_routes.character_mcp_service, "execute_action", execute)

    novel_conflict = client.post(
        "/api/characters/mcp/execute",
        json={
            "action": "create",
            "novel_id": 2,
            "parameters": {"novel_id": 1, "name": "冲突"},
        },
    )
    character_conflict = client.post(
        "/api/characters/mcp/execute",
        json={
            "action": "update",
            "character_id": 3,
            "parameters": {"character_id": 1, "name": "冲突"},
        },
    )

    assert novel_conflict.status_code == 422
    assert character_conflict.status_code == 422
    execute.assert_not_awaited()


def test_successful_direct_mcp_mutation_returns_json_safe_response(character_mcp_api):
    client, db = character_mcp_api

    created = client.post(
        "/api/characters/mcp/execute",
        json={
            "action": "create",
            "parameters": {"novel_id": 2, "name": "安全创建", "skills": ["剑术"]},
        },
    )
    listed = client.post(
        "/api/characters/mcp/execute",
        json={"action": "list", "parameters": {"novel_id": 2}},
    )

    assert created.status_code == 200
    assert created.json()["success"] is True
    assert created.json()["result"]["character"]["name"] == "安全创建"
    assert listed.status_code == 200
    assert all(
        isinstance(character, dict)
        for character in listed.json()["result"]["characters"]
    )
    db.expire_all()
    assert db.query(Character).filter_by(novel_id=2, name="安全创建").one()


def test_create_with_failed_ai_analysis_does_not_leave_committed_character(
    character_mcp_api,
    monkeypatch,
):
    """可选 AI 分析失败时，创建操作必须整体回滚，不能假失败真写入。"""

    client, db = character_mcp_api
    monkeypatch.setattr(
        character_routes.character_mcp_service,
        "_perform_ai_analysis",
        AsyncMock(side_effect=RuntimeError("模型不可用")),
    )

    response = client.post(
        "/api/characters/mcp/execute",
        json={
            "action": "create",
            "parameters": {"novel_id": 2, "name": "不应残留"},
            "context": "创建后执行分析",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    db.expire_all()
    assert db.query(Character).filter_by(novel_id=2, name="不应残留").count() == 0
