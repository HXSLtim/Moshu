"""MCP 审计与输入预算的回归测试。"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整 SQLAlchemy 模型
from app.api.dependencies import get_current_user
from app.db.base import Base, get_db
from app.main import app
from app.models.character import Character
from app.models.character_schemas import CharacterCreate
from app.models.novel import Novel
from app.models.user import User
from app.models.worldview_schemas import UnifiedMCPAction, UnifiedMCPResponse
from app.services.mcp_audit_service import MCPAuditLog, mcp_audit_service
from app.services.unified_mcp_service import unified_mcp_service


@pytest.fixture
def audit_db():
    """创建包含审计表的独立内存数据库。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(bind=engine)
    db = testing_session()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_audit_serializes_orm_result(audit_db):
    """成功结果携带 ORM 对象时也必须可持久化为 JSON。"""
    action = UnifiedMCPAction(
        target_type="character",
        action="create",
        novel_id=1,
        parameters={"name": "沈砚"},
    )
    character = Character(id=7, novel_id=1, name="沈砚", skills=["剑术"])
    response = UnifiedMCPResponse(
        success=True,
        target_type="character",
        action="create",
        target_id=7,
        result={"character": character},
        message="创建成功",
        timestamp=datetime.utcnow(),
    )

    await mcp_audit_service.log_mcp_operation(
        audit_db,
        action,
        response,
        user_id=3,
    )

    stored = audit_db.query(MCPAuditLog).one()
    assert stored.result_data["character"]["name"] == "沈砚"
    assert stored.result_data["character"]["skills"] == ["剑术"]


def test_error_analysis_uses_bounded_user_query(audit_db):
    """错误分析不应因缺失 SQL 表达式导入而失败，且只统计当前用户。"""
    audit_db.add_all(
        [
            MCPAuditLog(
                user_id=1,
                target_type="character",
                action="create",
                success=False,
                error_message="当前用户错误",
            ),
            MCPAuditLog(
                user_id=2,
                target_type="character",
                action="create",
                success=False,
                error_message="其他用户错误",
            ),
        ]
    )
    audit_db.commit()

    result = mcp_audit_service.get_error_analysis(audit_db, user_id=1)

    assert result["total_errors"] == 1
    assert "当前用户错误" in result["error_patterns"]
    assert "其他用户错误" not in result["error_patterns"]


@pytest.fixture
def reused_novel_audit_api(audit_db):
    """构造旧小说删除后主键被另一用户复用的真实 API 场景。"""
    old_owner = User(
        id=1,
        username="audit-old-owner",
        email="audit-old@example.com",
        hashed_password="not-used",
    )
    current_owner = User(
        id=2,
        username="audit-current-owner",
        email="audit-current@example.com",
        hashed_password="not-used",
    )
    old_novel = Novel(id=77, title="旧用户小说", user_id=old_owner.id)
    audit_db.add_all([old_owner, current_owner, old_novel])
    audit_db.commit()
    old_owner_id = old_owner.id
    current_owner_id = current_owner.id

    audit_db.add(
        MCPAuditLog(
            user_id=old_owner_id,
            novel_id=old_novel.id,
            target_type="character",
            action="旧用户操作",
            success=False,
            error_message="旧用户敏感错误",
        )
    )
    audit_db.commit()
    audit_db.delete(old_novel)
    audit_db.commit()
    audit_db.expunge_all()

    reused_novel = Novel(id=77, title="当前用户小说", user_id=current_owner_id)
    audit_db.add_all(
        [
            reused_novel,
            MCPAuditLog(
                user_id=current_owner_id,
                novel_id=reused_novel.id,
                target_type="character",
                action="当前用户操作",
                success=False,
                error_message="当前用户错误",
            ),
            MCPAuditLog(
                user_id=current_owner_id,
                novel_id=None,
                target_type="character",
                action="无小说操作",
                success=True,
            ),
        ]
    )
    audit_db.commit()

    def override_db():
        yield audit_db

    async def override_user():
        return audit_db.get(User, current_owner_id)

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        with TestClient(app) as client:
            yield client, audit_db
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_audit_service_requires_user_and_current_novel_ownership(
    reused_novel_audit_api,
):
    """服务层必须同时约束审计用户和小说当前所有权。"""
    _, db = reused_novel_audit_api

    current_history = mcp_audit_service.get_user_operation_history(db, user_id=2)
    current_novel_history = mcp_audit_service.get_novel_operation_history(
        db,
        user_id=2,
        novel_id=77,
    )
    old_history = mcp_audit_service.get_user_operation_history(db, user_id=1)
    current_stats = mcp_audit_service.get_operation_statistics(
        db,
        user_id=2,
        novel_id=77,
    )
    current_errors = mcp_audit_service.get_error_analysis(db, user_id=2)
    old_stats = mcp_audit_service.get_operation_statistics(db, user_id=1)
    old_errors = mcp_audit_service.get_error_analysis(db, user_id=1)

    assert {log.action for log in current_history} == {"当前用户操作", "无小说操作"}
    assert [log.action for log in current_novel_history] == ["当前用户操作"]
    assert old_history == []
    assert current_stats["operation_summary"]["total_operations"] == 1
    assert current_errors["total_errors"] == 1
    assert "当前用户错误" in current_errors["error_patterns"]
    assert "旧用户敏感错误" not in current_errors["error_patterns"]
    assert old_stats["operation_summary"]["total_operations"] == 0
    assert old_errors["total_errors"] == 0


def test_audit_routes_do_not_leak_reused_novel_records(reused_novel_audit_api):
    """所有公开审计入口都不能泄漏复用 ID 对应的旧租户记录。"""
    client, _ = reused_novel_audit_api
    previous_counters = dict(unified_mcp_service._operation_counters)
    unified_mcp_service._operation_counters.clear()
    unified_mcp_service._operation_counters.update({(1, 77): 4, (2, 77): 1})
    try:
        history = client.get("/api/mcp/audit/history")
        novel_history = client.get("/api/mcp/audit/novel/77/history")
        statistics = client.get("/api/mcp/audit/statistics")
        novel_statistics = client.get("/api/mcp/audit/novel/77/statistics")
        errors = client.get("/api/mcp/audit/errors")
        performance = client.get("/api/mcp/monitoring/performance")
    finally:
        unified_mcp_service._operation_counters.clear()
        unified_mcp_service._operation_counters.update(previous_counters)

    assert history.status_code == 200
    assert {item["action"] for item in history.json()["operations"]} == {
        "当前用户操作",
        "无小说操作",
    }
    assert novel_history.status_code == 200
    assert [item["action"] for item in novel_history.json()["operations"]] == [
        "当前用户操作"
    ]
    assert statistics.json()["statistics"]["operation_summary"]["total_operations"] == 2
    assert novel_statistics.json()["statistics"]["operation_summary"]["total_operations"] == 1
    assert errors.json()["error_analysis"]["total_errors"] == 1
    assert "旧用户敏感错误" not in errors.text
    assert performance.json()["recent_performance"]["last_24h_operations"] == 2
    assert performance.json()["system_status"]["current_concurrent_operations"] == {
        "77": 1
    }
    assert performance.json()["system_status"]["total_active_operations"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/mcp/audit/history?limit=0",
        "/api/mcp/audit/history?limit=501",
        "/api/mcp/audit/novel/0/history",
        "/api/mcp/audit/novel/77/history?limit=501",
        "/api/mcp/audit/statistics?days=0",
        "/api/mcp/audit/statistics?days=366",
        "/api/mcp/audit/novel/0/statistics",
        "/api/mcp/audit/novel/77/statistics?days=366",
        "/api/mcp/audit/errors?days=0",
    ],
)
def test_audit_route_query_bounds(reused_novel_audit_api, path):
    """审计查询参数必须在进入数据库前拒绝无界或无效取值。"""
    client, _ = reused_novel_audit_api

    response = client.get(path)

    assert response.status_code == 422


def test_unified_mcp_action_rejects_unbounded_nested_parameters():
    """嵌套参数不能绕过字段条目数限制制造无界上下文。"""
    with pytest.raises(ValidationError, match="20000"):
        UnifiedMCPAction(
            target_type="character",
            action="create",
            novel_id=1,
            parameters={"background": "长" * 20_001},
        )


def test_character_card_rejects_unbounded_context():
    """角色卡进入生成链路前应限制长文本与嵌套关系总量。"""
    with pytest.raises(ValidationError):
        CharacterCreate(
            novel_id=1,
            name="沈砚",
            background="长" * 8_001,
        )

    with pytest.raises(ValidationError, match="20000"):
        CharacterCreate(
            novel_id=1,
            name="沈砚",
            relationships={"宿敌": "长" * 20_001},
        )
