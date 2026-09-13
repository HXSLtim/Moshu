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
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, JSON, String, Integer, text
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.db.base import Base, engine as default_engine
from app.db.integrity import verify_existing_references
from app.db.story_bible_integrity import STORY_FACT_CHECKS, STORY_EVENT_CHECKS, preflight_story_bible
from app.db.sqlite_compat import ensure_sqlite_compatibility
from app.db.memory_backfill import backfill_current_chapter_revisions, current_chapter_snapshots
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

    with engine.connect() as connection:
        verify_existing_references(connection)
        preflight_story_bible(connection)
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
        # 完整旧库先预检，只有小说表的空章节旧库交由 create_all 补表。
        if _table_exists(engine, "chapters") and _table_exists(engine, "novels"):
            with engine.connect() as connection:
                current_chapter_snapshots(connection)
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            # create_all 不会给既有表补列，旧版无迁移历史的对话表需显式演进。
            if "context_manifest" not in {column["name"] for column in inspect(connection).get_columns("writing_turns")}:
                Operations(MigrationContext.configure(connection)).add_column(
                    "writing_turns", Column("context_manifest", JSON(), nullable=True),
                )
            # 无迁移历史旧库按显式字段演进，不能create_all后直接假称现有列已升级。
            operations = Operations(MigrationContext.configure(connection))
            additions = {
                "writing_turns": [
                    Column("novel_lifecycle_id", String(32), nullable=True),
                    Column("chapter_lifecycle_id", String(32), nullable=True),
                    Column("base_version", Integer(), nullable=True),
                    Column("result", JSON(), nullable=True),
                    Column("proposal_id", String(36), nullable=True),
                    Column("execution", JSON(), nullable=True),
                ],
                "writing_proposals": [Column("execution_job_id", String(36), nullable=True)],
                "story_entities": [Column("description", String(500), nullable=False, server_default="")],
                "story_facts": [
                    Column("entity_id", String(36), nullable=True),
                    Column("value_entity_id", String(36), nullable=True),
                    Column("novel_lifecycle_id", String(32), nullable=True),
                    Column("origin", String(20), nullable=False, server_default="author"),
                    Column("source_refs", JSON(), nullable=False, server_default="[]"),
                    Column("source_status", String(20), nullable=False, server_default="ready"),
                    Column("version", Integer(), nullable=False, server_default="1"),
                ],
            }
            for table_name, columns in additions.items():
                existing = {column["name"] for column in inspect(connection).get_columns(table_name)}
                for column in columns:
                    if column.name not in existing:
                        operations.add_column(table_name, column)
            # 无 Alembic 历史的旧库也必须把事实绑定到当前作品生命周期，
            # 否则整数小说 ID 删除重建后会留下无法核验的旧事实。
            if "story_facts" in inspect(connection).get_table_names() and "novels" in inspect(connection).get_table_names():
                connection.execute(text(
                    "UPDATE story_facts SET novel_lifecycle_id = "
                    "(SELECT rag_lifecycle_id FROM novels WHERE novels.id = story_facts.novel_id) "
                    "WHERE story_facts.novel_lifecycle_id IS NULL"
                ))
            if "ix_story_facts_entity_id" not in {index["name"] for index in inspect(connection).get_indexes("story_facts")}:
                operations.create_index("ix_story_facts_entity_id", "story_facts", ["entity_id"])
            backfill_current_chapter_revisions(connection)
        # create_all不会修改已有表的检查约束，旧库必须与迁移路径获得同一写入约束。
        with engine.connect() as connection:
            sqlite = connection.dialect.name == "sqlite"
            previous_fk = connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() if sqlite else None
            connection.commit()
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
            try:
                with connection.begin():
                    preflight_story_bible(connection)
                    operations = Operations(MigrationContext.configure(connection))
                    for table, checks in (("story_facts", STORY_FACT_CHECKS), ("story_events", STORY_EVENT_CHECKS)):
                        existing = {item["name"] for item in inspect(connection).get_check_constraints(table)}
                        missing = {name: expression for name, expression in checks.items() if name not in existing}
                        if missing:
                            with operations.batch_alter_table(table) as batch:
                                for name, expression in missing.items():
                                    batch.create_check_constraint(name, expression)
                    if sqlite and connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                        raise ValueError("旧库升级后存在外键冲突，请从备份核对")
            finally:
                if sqlite:
                    connection.rollback()
                    connection.exec_driver_sql(f"PRAGMA foreign_keys={int(previous_fk or 0)}")
                    connection.commit()
        command.stamp(config, "head")
        print("[SUCCESS] 旧库已完成补齐并标记为当前迁移版本 (stamp head)。")
        return

    print("[INFO] 检测到空库，按最新迁移建表...")
    command.upgrade(config, "head")
    print("[SUCCESS] 数据库初始化完成！")
    print(f"[INFO] 创建的表：{', '.join(sorted(Base.metadata.tables.keys()))}")


if __name__ == "__main__":
    initialize_database()
