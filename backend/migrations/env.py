"""Alembic 迁移环境。

连接信息与模型元数据统一来自应用配置与模型注册表:
- 引擎优先使用调用方通过 ``config.attributes["engine"]`` 注入的实例
  (init_db.py 与测试用),否则按 settings.database_url 自建。
- autogenerate 对比的元数据来自 app.db.base.Base,通过导入
  ``app.models`` 注册全部表。
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, engine_from_config, pool

from alembic import context

# 保证在 backend/ 任意子目录执行 alembic 命令时都能导入 app 包。
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402, F401  # 注册完整模型元数据

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_engine():
    """优先使用注入引擎,否则按应用配置自建。"""
    injected = config.attributes.get("engine")
    if injected is not None:
        return injected

    url = os.environ.get("DATABASE_URL", settings.database_url)
    connect_args = (
        {"check_same_thread": False} if url.startswith("sqlite") else {}
    )
    return create_engine(
        url,
        connect_args=connect_args,
        poolclass=pool.NullPool,
    )


def run_migrations_offline() -> None:
    """离线模式:只生成 SQL,不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url") or settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式:通过真实连接执行迁移。"""
    connectable = _resolve_engine()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
