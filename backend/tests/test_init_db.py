"""数据库初始化路径(空库/旧库/已管理库)回归测试。"""

from sqlalchemy import create_engine, inspect, text

from init_db import _alembic_config, initialize_database
from alembic.script import ScriptDirectory
from tests.test_sqlite_compat import OLD_CHAPTERS_SCHEMA


def _file_engine(tmp_path, name: str):
    return create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )


def _current_head(engine) -> str:
    """当前迁移链的 head 版本号。"""
    return ScriptDirectory.from_config(_alembic_config(engine)).get_current_head()


def test_empty_database_is_created_via_migrations(tmp_path):
    """空库应通过基线迁移建全表并写入版本。"""
    engine = _file_engine(tmp_path, "empty.db")

    initialize_database(engine)

    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    assert {"novels", "chapters", "users", "mcp_audit_logs"} <= tables
    with engine.connect() as connection:
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert version == _current_head(engine)
    engine.dispose()


def test_legacy_database_is_backfilled_and_stamped(tmp_path):
    """无版本表的旧库应补齐结构、补建缺表并标记当前版本。"""
    engine = _file_engine(tmp_path, "legacy.db")
    with engine.begin() as connection:
        connection.execute(text(OLD_CHAPTERS_SCHEMA))
        connection.execute(text("CREATE TABLE novels (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                "INSERT INTO chapters (id, novel_id, chapter_number, title, content) "
                "VALUES (1, 7, 1, '第一章', '正文')"
            )
        )

    initialize_database(engine)

    tables = set(inspect(engine).get_table_names())
    assert "alembic_version" in tables
    # 兼容补齐：旧 chapters 表获得 version 列。
    columns = {
        column["name"] for column in inspect(engine).get_columns("chapters")
    }
    assert "version" in columns
    # create_all 兜底：缺失的新表被补建。
    assert "mcp_audit_logs" in tables
    with engine.connect() as connection:
        version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        content = connection.execute(
            text("SELECT content FROM chapters WHERE id = 1")
        ).scalar()
    assert version == _current_head(engine)
    assert content == "正文"
    engine.dispose()


def test_managed_database_upgrade_is_idempotent(tmp_path):
    """已受管理的库重复初始化应无操作、无异常。"""
    engine = _file_engine(tmp_path, "managed.db")
    initialize_database(engine)
    first_version = None
    with engine.connect() as connection:
        first_version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()

    initialize_database(engine)

    with engine.connect() as connection:
        second_version = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
    assert first_version == second_version == _current_head(engine)
    engine.dispose()
