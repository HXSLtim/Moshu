"""旧版 SQLite 数据库的幂等兼容迁移。"""

from dataclasses import dataclass
from typing import Sequence
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


CHAPTER_UNIQUE_INDEX = "uq_chapters_novel_number"
CHAPTER_IDENTITY_COLUMNS = ("novel_id", "chapter_number")
NOVEL_RAG_LIFECYCLE_INDEX = "uq_novels_rag_lifecycle_id"
CHAPTER_RAG_LIFECYCLE_INDEX = "uq_chapters_rag_lifecycle_id"


class SQLiteCompatibilityMigrationError(RuntimeError):
    """无法在不破坏现有数据的前提下完成兼容迁移。"""


@dataclass(frozen=True)
class SQLiteCompatibilityResult:
    """兼容迁移执行结果。"""

    dialect: str
    novels_table_found: bool = False
    chapters_table_found: bool = False
    version_added: bool = False
    unique_index_created: bool = False
    novel_rag_lifecycle_added: bool = False
    novel_rag_revision_added: bool = False
    chapter_rag_lifecycle_added: bool = False


def _has_chapter_identity_unique_index(inspector) -> bool:
    """判断章节身份列是否已经受唯一约束或唯一索引保护。"""

    expected = list(CHAPTER_IDENTITY_COLUMNS)
    for constraint in inspector.get_unique_constraints("chapters"):
        if constraint.get("column_names") == expected:
            return True
    for index in inspector.get_indexes("chapters"):
        if index.get("unique") and index.get("column_names") == expected:
            return True
    return False


def _has_unique_index(inspector, table_name: str, column_name: str) -> bool:
    """判断单列是否已经由唯一约束或唯一索引保护。"""
    for constraint in inspector.get_unique_constraints(table_name):
        if constraint.get("column_names") == [column_name]:
            return True
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and index.get("column_names") == [column_name]:
            return True
    return False


def _populate_missing_lifecycle_ids(connection, table_name: str) -> None:
    """为旧数据逐行补齐随机生命周期，避免主键复用继承旧身份。"""
    missing_ids = connection.execute(
        text(
            f"SELECT id FROM {table_name} "
            "WHERE rag_lifecycle_id IS NULL OR rag_lifecycle_id = ''"
        )
    ).scalars().all()
    for row_id in missing_ids:
        connection.execute(
            text(
                f"UPDATE {table_name} SET rag_lifecycle_id = :lifecycle_id "
                "WHERE id = :row_id"
            ),
            {"lifecycle_id": uuid4().hex, "row_id": row_id},
        )


def _format_duplicate_chapters(rows: Sequence) -> str:
    """将重复章节号压缩为可定位的错误信息。"""

    return ", ".join(
        f"novel_id={row.novel_id}, chapter_number={row.chapter_number}, count={row.duplicate_count}"
        for row in rows
    )


def ensure_sqlite_compatibility(engine: Engine) -> SQLiteCompatibilityResult:
    """为旧 SQLite chapters 表补齐版本列和章节号唯一索引。

    迁移先检查重复数据，再执行任何 DDL。若存在重复章节号，会明确失败并保持
    原有表结构与数据不变。非 SQLite 数据库不在此处执行结构迁移。
    """

    dialect = engine.dialect.name
    if dialect != "sqlite":
        return SQLiteCompatibilityResult(dialect=dialect)

    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        novels_table_found = "novels" in table_names
        chapters_table_found = "chapters" in table_names
        if not novels_table_found and not chapters_table_found:
            return SQLiteCompatibilityResult(dialect=dialect)

        chapter_columns = (
            {column["name"] for column in inspector.get_columns("chapters")}
            if chapters_table_found
            else set()
        )
        if chapters_table_found:
            missing_identity_columns = set(CHAPTER_IDENTITY_COLUMNS) - chapter_columns
            if missing_identity_columns:
                missing = ", ".join(sorted(missing_identity_columns))
                raise SQLiteCompatibilityMigrationError(
                    f"旧 SQLite chapters 表缺少必要列：{missing}；无法自动兼容，请先备份并人工迁移。"
                )

            duplicate_rows = connection.execute(
                text(
                    """
                    SELECT novel_id, chapter_number, COUNT(*) AS duplicate_count
                    FROM chapters
                    GROUP BY novel_id, chapter_number
                    HAVING COUNT(*) > 1
                    ORDER BY novel_id, chapter_number
                    LIMIT 20
                    """
                )
            ).all()
            if duplicate_rows:
                details = _format_duplicate_chapters(duplicate_rows)
                raise SQLiteCompatibilityMigrationError(
                    "检测到同一小说内存在重复章节号，无法安全创建唯一索引；"
                    f"数据未修改。重复项：{details}"
                )

        novel_rag_lifecycle_added = False
        novel_rag_revision_added = False
        if novels_table_found:
            novel_columns = {
                column["name"] for column in inspector.get_columns("novels")
            }
            if "rag_lifecycle_id" not in novel_columns:
                connection.execute(
                    text("ALTER TABLE novels ADD COLUMN rag_lifecycle_id VARCHAR(32)")
                )
                novel_rag_lifecycle_added = True
            if "rag_revision" not in novel_columns:
                connection.execute(
                    text(
                        "ALTER TABLE novels "
                        "ADD COLUMN rag_revision INTEGER NOT NULL DEFAULT 1"
                    )
                )
                novel_rag_revision_added = True
            _populate_missing_lifecycle_ids(connection, "novels")
            if not _has_unique_index(inspector, "novels", "rag_lifecycle_id"):
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX {NOVEL_RAG_LIFECYCLE_INDEX} "
                        "ON novels (rag_lifecycle_id)"
                    )
                )

        version_added = False
        chapter_rag_lifecycle_added = False
        if chapters_table_found and "version" not in chapter_columns:
            connection.execute(
                text(
                    "ALTER TABLE chapters "
                    "ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
            )
            version_added = True

        if chapters_table_found and "rag_lifecycle_id" not in chapter_columns:
            connection.execute(
                text("ALTER TABLE chapters ADD COLUMN rag_lifecycle_id VARCHAR(32)")
            )
            chapter_rag_lifecycle_added = True
        if chapters_table_found:
            _populate_missing_lifecycle_ids(connection, "chapters")
            if not _has_unique_index(inspector, "chapters", "rag_lifecycle_id"):
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX {CHAPTER_RAG_LIFECYCLE_INDEX} "
                        "ON chapters (rag_lifecycle_id)"
                    )
                )

        unique_index_created = False
        if chapters_table_found and not _has_chapter_identity_unique_index(inspector):
            connection.execute(
                text(
                    f"CREATE UNIQUE INDEX {CHAPTER_UNIQUE_INDEX} "
                    "ON chapters (novel_id, chapter_number)"
                )
            )
            unique_index_created = True

        return SQLiteCompatibilityResult(
            dialect=dialect,
            novels_table_found=novels_table_found,
            chapters_table_found=chapters_table_found,
            version_added=version_added,
            unique_index_created=unique_index_created,
            novel_rag_lifecycle_added=novel_rag_lifecycle_added,
            novel_rag_revision_added=novel_rag_revision_added,
            chapter_rag_lifecycle_added=chapter_rag_lifecycle_added,
        )
