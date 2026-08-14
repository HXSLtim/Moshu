"""
Pytest配置文件
定义测试夹具（fixtures）
"""
import os

# 安全配置不提供运行时默认密钥；测试进程必须显式注入隔离值。
os.environ.setdefault(
    "SECRET_KEY",
    "pytest-only-random-secret-key-with-at-least-32-characters",
)

import pytest
import asyncio
from typing import AsyncGenerator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.api.dependencies import get_current_user
from app.main import app
from app.core.config import settings
from app.db.base import Base, get_db
from app.models.novel import Novel
from app.models.user import User


def pytest_addoption(parser):
    """显式允许需要本机真实模型服务的集成测试。"""

    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行需要本机真实外部服务的集成测试",
    )


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def integration_client(request):
    """使用隔离数据库和真实模型服务的认证客户端。"""

    if not request.config.getoption("--run-integration"):
        pytest.skip("使用 --run-integration 运行真实服务集成测试")

    integration_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    integration_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=integration_engine,
    )
    Base.metadata.create_all(bind=integration_engine)

    setup_db = integration_session()
    user = User(
        id=1,
        username="integration-user",
        email="integration@example.com",
        hashed_password="not-used",
    )
    setup_db.add(user)
    setup_db.add(
        Novel(
            id=1,
            title="真实模型集成测试",
            worldview="这是一个用于本机模型连通性验证的简短世界观。",
            user_id=1,
        )
    )
    setup_db.commit()

    def override_db():
        db = integration_session()
        try:
            yield db
        finally:
            db.close()

    async def override_user():
        return user

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        setup_db.close()
        Base.metadata.drop_all(bind=integration_engine)
        integration_engine.dispose()


@pytest.fixture
def test_novel_id():
    """测试用的小说ID"""
    return 1


@pytest.fixture
def test_prompt():
    """测试用的剧情提示词"""
    return "主角在魔法塔顶与导师决裂，雷电在天空中闪烁"


@pytest.fixture
def test_worldview_rules():
    """测试用的世界观规则"""
    return {
        "魔法等级上限": 9,
        "飞行速度上限": 100,
    }


@pytest.fixture
async def mock_openai_response():
    """模拟OpenAI API响应"""
    return {
        "worldview": "魔法塔顶，雷电交加，魔法能量在空气中涌动。",
        "character": "李明咬紧牙关，眼中闪过决绝的光芒。'导师，我不能再跟随你了！'他的声音在雷声中回荡。",
        "plot": "在魔法塔的最高层，李明终于对导师说出了藏在心底已久的话。雷电在天空中撕裂，映照出两人决裂的瞬间。"
    }
