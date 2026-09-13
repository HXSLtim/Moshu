"""旧 SQLite 兼容迁移回归测试。"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.sqlite_compat import (
    SQLiteCompatibilityMigrationError,
    SQLiteCompatibilityResult,
    ensure_sqlite_compatibility,
)


OLD_CHAPTERS_SCHEMA = """
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY,
    novel_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    word_count INTEGER,
    created_at DATETIME,
    updated_at DATETIME
)
"""


def _create_old_chapters_table(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(OLD_CHAPTERS_SCHEMA))


def test_old_sqlite_chapters_are_migrated_idempotently():
    engine = create_engine("sqlite://")
    _create_old_chapters_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chapters "
                "(id, novel_id, chapter_number, title, content) "
                "VALUES (1, 7, 1, '第一章', '正文'), (2, 7, 2, '第二章', '正文')"
            )
        )

    first = ensure_sqlite_compatibility(engine)
    second = ensure_sqlite_compatibility(engine)

    assert first.version_added is True
    assert first.unique_index_created is True
    assert first.chapter_rag_lifecycle_added is True
    assert second.version_added is False
    assert second.unique_index_created is False
    assert second.chapter_rag_lifecycle_added is False

    with engine.connect() as connection:
        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("chapters")
        }
        assert columns["version"]["nullable"] is False
        assert connection.execute(
            text("SELECT version FROM chapters ORDER BY id")
        ).scalars().all() == [1, 1]
        lifecycle_ids = connection.execute(
            text("SELECT rag_lifecycle_id FROM chapters ORDER BY id")
        ).scalars().all()
        assert all(len(item) == 32 for item in lifecycle_ids)
        assert len(set(lifecycle_ids)) == 2

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO chapters "
                    "(novel_id, chapter_number, title, content) "
                    "VALUES (7, 1, '重复章', '正文')"
                )
            )


def test_duplicate_chapter_numbers_fail_before_any_schema_change():
    engine = create_engine("sqlite://")
    _create_old_chapters_table(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chapters "
                "(id, novel_id, chapter_number, title, content) VALUES "
                "(1, 9, 3, '重复一', '正文一'), "
                "(2, 9, 3, '重复二', '正文二')"
            )
        )

    with pytest.raises(SQLiteCompatibilityMigrationError) as exc_info:
        ensure_sqlite_compatibility(engine)

    message = str(exc_info.value)
    assert "数据未修改" in message
    assert "novel_id=9, chapter_number=3, count=2" in message
    with engine.connect() as connection:
        assert "version" not in {
            column["name"] for column in inspect(connection).get_columns("chapters")
        }
        assert connection.execute(
            text("SELECT id, title FROM chapters ORDER BY id")
        ).all() == [(1, "重复一"), (2, "重复二")]
        assert not any(
            index.get("unique")
            for index in inspect(connection).get_indexes("chapters")
        )


def test_missing_chapters_table_and_non_sqlite_are_noops():
    sqlite_engine = create_engine("sqlite://")
    sqlite_result = ensure_sqlite_compatibility(sqlite_engine)
    assert sqlite_result.chapters_table_found is False

    non_sqlite_engine = MagicMock()
    non_sqlite_engine.dialect.name = "postgresql"
    postgres_result = ensure_sqlite_compatibility(non_sqlite_engine)
    assert postgres_result.dialect == "postgresql"
    non_sqlite_engine.begin.assert_not_called()


def test_old_sqlite_novels_receive_persistent_rag_identity_and_revision():
    """旧小说数据迁移后具有不可复用生命周期和单调世界观版本。"""
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE novels (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    worldview TEXT,
                    user_id INTEGER NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO novels (id, title, worldview, user_id) VALUES "
                "(1, '旧小说一', '世界观一', 7), (2, '旧小说二', '世界观二', 8)"
            )
        )

    first = ensure_sqlite_compatibility(engine)
    second = ensure_sqlite_compatibility(engine)

    assert first.novels_table_found is True
    assert first.novel_rag_lifecycle_added is True
    assert first.novel_rag_revision_added is True
    assert second.novel_rag_lifecycle_added is False
    assert second.novel_rag_revision_added is False
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT rag_lifecycle_id, rag_revision "
                "FROM novels ORDER BY id"
            )
        ).all()
        assert [row.rag_revision for row in rows] == [1, 1]
        assert all(len(row.rag_lifecycle_id) == 32 for row in rows)
        assert len({row.rag_lifecycle_id for row in rows}) == 2


def test_init_db_runs_compatibility_check_before_migration(monkeypatch):
    import init_db

    calls = []
    fake_engine = MagicMock()

    def fake_migrate(received_engine):
        calls.append(("migrate", received_engine))
        return SQLiteCompatibilityResult(dialect="sqlite")

    def fake_upgrade(config, revision):
        calls.append(("upgrade", revision))

    def fake_create_all(*, bind):
        calls.append(("create_all", bind))

    monkeypatch.setattr(init_db, "default_engine", fake_engine)
    monkeypatch.setattr(init_db, "verify_existing_references", lambda connection: calls.append(("preflight", connection)))
    monkeypatch.setattr(init_db, "preflight_story_bible", lambda connection: calls.append(("ledger_preflight", connection)))
    monkeypatch.setattr(init_db, "ensure_sqlite_compatibility", fake_migrate)
    # 空库：既无版本表也无应用表，应走 upgrade 建表而非 create_all。
    monkeypatch.setattr(init_db, "_table_exists", lambda engine, name: False)
    monkeypatch.setattr(init_db.Base.metadata, "create_all", fake_create_all)
    monkeypatch.setattr(init_db.command, "upgrade", fake_upgrade)

    init_db.initialize_database()

    assert calls == [
        ("preflight", fake_engine.connect.return_value.__enter__.return_value),
        ("ledger_preflight", fake_engine.connect.return_value.__enter__.return_value),
        ("migrate", fake_engine),
        ("upgrade", "head"),
    ]
