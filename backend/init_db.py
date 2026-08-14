"""数据库初始化与旧 SQLite 兼容迁移脚本。

职责分工:
- ``ensure_sqlite_compatibility``:旧库的列/索引级幂等补齐(无 Alembic 历史的库)。
- Alembic:空库建表与后续所有结构演进,是唯一演进入口。

三种库形态处理:
1. 空库 → ``alembic upgrade head`` 由基线迁移建全部表。
2. 旧库(有应用表但无 alembic_version)→ 兼容补齐 + ``create_all``
   补建缺失的新表 + ``alembic stamp head`` 标记为当前版本。
3. 已受 Alembic 管理的库 → ``alembic upgrade head``(无待执行迁移时为无操作)。
"""

from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.base import Base, engine as default_engine
from app.db.sqlite_compat import ensure_sqlite_compatibility
import app.models  # noqa: F401  # 导入完整模型注册表，确保关系和约束均被发现

BACKEND_DIR = Path(__file__).resolve().parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def _alembic_config(engine: Engine) -> Config:
    """构造 Alembic 配置并注入实际引擎，避免依赖工作目录与 ini 占位地址。"""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["engine"] = engine
    return config


def _table_exists(engine: Engine, table_name: str) -> bool:
    return table_name in set(inspect(engine).get_table_names())


def _report_compatibility(migration) -> None:
    """打印旧库兼容补齐结果。"""
    if migration.dialect != "sqlite":
        print(
            "[INFO] 非 SQLite 数据库跳过旧库兼容补齐，"
            "结构演进由 Alembic 统一管理。"
        )
        return
    if migration.novels_table_found or migration.chapters_table_found:
        print(
            "[INFO] SQLite 兼容检查完成："
            f"version_added={migration.version_added}, "
            f"unique_index_created={migration.unique_index_created}, "
            f"novel_rag_lifecycle_added={migration.novel_rag_lifecycle_added}, "
            f"novel_rag_revision_added={migration.novel_rag_revision_added}, "
            f"chapter_rag_lifecycle_added={migration.chapter_rag_lifecycle_added}"
        )


def initialize_database(engine: Optional[Engine] = None) -> None:
    """幂等地把数据库带到当前模型对应的最新迁移版本。

    engine 参数用于测试注入临时库；不传时使用应用默认引擎。
    """

    engine = engine or default_engine
    config = _alembic_config(engine)

    print("正在检查数据库兼容性...")
    migration = ensure_sqlite_compatibility(engine)
    _report_compatibility(migration)

    if _table_exists(engine, "alembic_version"):
        print("[INFO] 检测到 Alembic 版本表，执行增量升级...")
        command.upgrade(config, "head")
        print("[SUCCESS] 数据库已升级到最新迁移版本。")
        return

    if _table_exists(engine, "novels") or _table_exists(engine, "chapters"):
        # 旧库过渡：兼容补齐已保证旧表结构一致，create_all 只补建缺失的新表。
        print("[INFO] 检测到旧库，补建缺失表并标记当前迁移版本...")
        Base.metadata.create_all(bind=engine)
        command.stamp(config, "head")
        print("[SUCCESS] 旧库已完成补齐并标记为当前迁移版本 (stamp head)。")
        return

    print("[INFO] 检测到空库，按最新迁移建表...")
    command.upgrade(config, "head")
    print("[SUCCESS] 数据库初始化完成！")
    print(f"[INFO] 创建的表：{', '.join(sorted(Base.metadata.tables.keys()))}")


if __name__ == "__main__":
    initialize_database()
