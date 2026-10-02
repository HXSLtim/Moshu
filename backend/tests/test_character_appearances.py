"""角色出场 REST 端点回归——POST 响应完整性与单请求事务纪律。

背景:POST /appearances 曾在两次 CRUD commit 后用 ORM ``__dict__`` 构造响应,
第二次 commit 过期清空 ``__dict__`` 导致缺 id/character_id/chapter_id/created_at
而 500,且失败外观下数据已落库(真机书 8 积三条重复出场)。
"""

from unittest.mock import patch

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
from app.models.character import Character, CharacterAppearance
from app.models.novel import Chapter, Novel
from app.models.user import User


@pytest.fixture
def appearances_api():
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
            User(id=1, username="owner", email="owner@example.com", hashed_password="x"),
            Novel(id=1, title="出场回归书", user_id=1),
        ]
    )
    setup_db.commit()
    setup_db.add_all(
        [
            Chapter(id=1, novel_id=1, chapter_number=1, title="第一章", content="正文"),
            Chapter(id=2, novel_id=1, chapter_number=2, title="第二章", content="正文"),
            Character(id=1, novel_id=1, name="程砚"),
        ]
    )
    setup_db.commit()
    current_user = setup_db.get(User, 1)

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


def _post_appearance(client, character_id=1, chapter_id=1, **overrides):
    payload = {
        "character_id": character_id,
        "chapter_id": chapter_id,
        "appearance_type": "main",
        "description": "抱着一摞书从廊下经过",
        "importance_in_chapter": 8,
        "status_changes": {"状态": "初登场"},
    }
    payload.update(overrides)
    return client.post("/api/characters/appearances", json=payload)


def test_create_appearance_returns_complete_response(appearances_api):
    """POST 必须成功且响应字段齐全——曾是 500 的主回归。"""
    client, _ = appearances_api

    response = _post_appearance(client)

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["id"] > 0
    assert data["character_id"] == 1
    assert data["chapter_id"] == 1
    assert data["appearance_type"] == "main"
    assert data["description"] == "抱着一摞书从廊下经过"
    assert data["importance_in_chapter"] == 8
    assert data["status_changes"] == {"状态": "初登场"}
    assert data["character_name"] == "程砚"
    assert data["chapter_number"] == 1
    assert data["created_at"] is not None


def test_create_appearance_updates_last_appearance_chapter(appearances_api):
    """成功创建出场后,角色最后出现章节同步推进。"""
    client, db = appearances_api

    response = _post_appearance(client, chapter_id=2)
    assert response.status_code == 201, response.text

    db.expire_all()
    character = db.get(Character, 1)
    assert character.last_appearance_chapter == 2


def test_failed_step_leaves_no_partial_appearance(appearances_api):
    """出场落库与最后章节更新必须同生共死:中途任一步崩,库不残留。"""
    client, db = appearances_api

    with patch.object(
        character_routes.character_crud,
        "update_character_last_appearance",
        side_effect=RuntimeError("更新最后章节失败"),
    ):
        response = _post_appearance(client)

    assert response.status_code == 500

    db.expire_all()
    assert db.query(CharacterAppearance).count() == 0
    character = db.get(Character, 1)
    assert character.last_appearance_chapter is None


def test_timeline_serializes_created_appearance(appearances_api):
    """时间线端点对已建出场的序列化字段齐全,与创建响应一致。"""
    client, _ = appearances_api

    created = _post_appearance(client)
    assert created.status_code == 201, created.text

    response = client.get("/api/characters/1/timeline")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["character_id"] == 1
    assert data["character_name"] == "程砚"
    appearances = data["appearances"]
    assert len(appearances) == 1
    entry = appearances[0]
    assert entry["id"] == created.json()["id"]
    assert entry["character_name"] == "程砚"
    assert entry["chapter_number"] == 1
    assert entry["chapter_id"] == 1
    assert entry["created_at"] is not None


@pytest.mark.parametrize(
    "payload, detail",
    [
        ({"character_id": 999, "chapter_id": 1}, "角色不存在"),
        ({"character_id": 1, "chapter_id": 999}, "章节不存在"),
    ],
)
def test_create_appearance_rejects_missing_targets(appearances_api, payload, detail):
    """角色或章节不存在时 404,且不落任何出场记录。"""
    client, db = appearances_api

    response = _post_appearance(client, **payload)

    assert response.status_code == 404
    assert detail in response.json()["detail"]
    db.expire_all()
    assert db.query(CharacterAppearance).count() == 0
