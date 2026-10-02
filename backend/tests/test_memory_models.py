"""原文快照迁移、不可覆写与聚合清理的隔离数据库回归。"""
from hashlib import sha256
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.memory_backfill import MemoryBackfillError, backfill_current_chapter_revisions
from app.models import Chapter, ChapterDigest, ChapterRevision, DerivedJob, Novel, User
from init_db import _alembic_config, initialize_database
from tests.test_sqlite_compat import OLD_CHAPTERS_SCHEMA


def _seed(engine):
    with Session(engine) as db:
        user = User(username="memory-author", email="memory@example.com", hashed_password="unused")
        db.add(user)
        db.flush()
        # 旧 schema 没有 review_mode 列,种子数据用裸 SQL 只写当时的列。
        db.execute(text("INSERT INTO novels (title, user_id, rag_lifecycle_id) VALUES ('原书', :uid, :lid)"),
                  {"uid": user.id, "lid": "0" * 32})
        novel_id = db.execute(text("SELECT id FROM novels")).scalars().one()
        chapter = Chapter(novel_id=novel_id, chapter_number=2, title="旧章名", content="\n正文 {原样}\r\n e\u0301 🐈\n", version=7)
        db.add(chapter)
        db.commit()
        return novel_id, chapter.id


def test_memory_upgrade_preserves_source_and_backfills_only_current_version(tmp_path):
    """升级、幂等回填和回退均不修改作者表的任何原字段。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    config = _alembic_config(engine)
    command.upgrade(config, "f7a91b2c340d")
    _seed(engine)
    with engine.connect() as connection:
        before = {table: connection.execute(text(f"SELECT * FROM {table}")).mappings().all() for table in ("novels", "chapters")}
    command.upgrade(config, "head")
    with engine.begin() as connection:
        snapshot = connection.execute(text("SELECT * FROM chapter_revisions")).mappings().one()
        assert UUID(snapshot["id"])
        chapter = before["chapters"][0]
        assert snapshot["version"] == 7
        for key in ("title", "content", "chapter_number", "novel_id"):
            assert snapshot[key] == chapter[key]
        assert snapshot["chapter_lifecycle_id"] == chapter["rag_lifecycle_id"]
        assert snapshot["novel_lifecycle_id"] == before["novels"][0]["rag_lifecycle_id"]
        assert snapshot["content_hash"] == sha256(chapter["content"].encode()).hexdigest()
        assert backfill_current_chapter_revisions(connection) == 0
        for table in ("derived_jobs", "chapter_digests"):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    initialize_database(engine)
    command.downgrade(config, "f7a91b2c340d")
    assert "chapter_revisions" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        for table, rows in before.items():
            assert connection.execute(text(f"SELECT * FROM {table}")).mappings().all() == rows
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM chapter_revisions")).scalar_one() == 1
    engine.dispose()


def test_legacy_backfill_is_idempotent_and_does_not_queue_jobs(tmp_path):
    """无 Alembic 历史的完整旧库经 create_all/stamp 同样得到一次快照。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    command.upgrade(_alembic_config(engine), "f7a91b2c340d")
    _seed(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    initialize_database(engine)
    initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM chapter_revisions")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM derived_jobs")).scalar_one() == 0
    engine.dispose()


def test_legacy_orphan_chapter_is_reported_without_deleting_manuscript(tmp_path):
    """孤儿章节必须报出定位信息，不能伪造父作品或悄悄漏掉原文。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'orphan.db'}")
    with engine.begin() as connection:
        connection.execute(text(OLD_CHAPTERS_SCHEMA))
        connection.execute(text("CREATE TABLE novels (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO chapters (id, novel_id, chapter_number, title, content) VALUES (1, 99, 1, '孤章', '不能丢')"))
    with pytest.raises(ValueError, match="chapters.novel_id: 1 条孤儿"):
        initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT content FROM chapters")).scalar_one() == "不能丢"
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    novel_id, chapter_id = _seed(engine)
    with engine.begin() as connection:
        backfill_current_chapter_revisions(connection)
    with Session(engine) as db:
        revision = db.scalars(select(ChapterRevision)).one()
        db.add_all([
            DerivedJob(novel_id=novel_id, novel_lifecycle_id=revision.novel_lifecycle_id, source_revision=revision, recipe_version="test-v1"),
            ChapterDigest(novel_id=novel_id, chapter_id=chapter_id, source_revision=revision, recipe_version="test-v1", summary="旧简介"),
        ])
        db.commit()
        yield db, novel_id, chapter_id, revision
    engine.dispose()


@pytest.mark.parametrize("delete_kind", ["chapter", "novel"])
def test_aggregate_delete_cleans_revisions_jobs_and_digests(memory_db, delete_kind):
    """SQLite 未启用外键时也能沿单一 ORM 拥有链完整清理。"""
    db, novel_id, chapter_id, revision = memory_db
    old_revision_id = revision.id
    db.delete(db.get(Chapter, chapter_id) if delete_kind == "chapter" else db.get(Novel, novel_id))
    db.commit()
    for model in (ChapterRevision, DerivedJob, ChapterDigest):
        assert db.query(model).count() == 0
    assert db.get(ChapterRevision, old_revision_id) is None
    if delete_kind == "chapter":
        db.add(Chapter(id=chapter_id, novel_id=novel_id, chapter_number=2, title="新章", content="新正文"))
        db.commit()
        assert db.get(Chapter, chapter_id).revisions == []


def test_revision_cannot_be_overwritten(memory_db):
    """更新 ORM 快照字段会失败，关系集合新增不误报。"""
    db, _, _, revision = memory_db
    original = revision.content
    revision.content = "覆盖旧稿"
    with pytest.raises(ValueError, match="原文版本不可覆写"):
        db.commit()
    db.rollback()
    assert revision.content == original


def test_backfill_rejects_conflicting_existing_snapshot(memory_db):
    """同版本正文被非标准路径篡改时不能覆盖既有历史。"""
    db, _, chapter_id, _ = memory_db
    db.execute(text("UPDATE chapters SET content = '版本未变的不同正文' WHERE id = :id"), {"id": chapter_id})
    db.commit()
    with pytest.raises(MemoryBackfillError, match="当前版本与历史快照不一致"):
        backfill_current_chapter_revisions(db.connection())


def test_job_uniqueness_rejects_duplicate_recipe(memory_db):
    """同来源同配方的重复任务由数据库唯一约束兜底。"""
    db, novel_id, _, revision = memory_db
    db.add(DerivedJob(novel_id=novel_id, novel_lifecycle_id=revision.novel_lifecycle_id, source_revision_id=revision.id, recipe_version="test-v1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("field", ["novel_id", "chapter_lifecycle_id", "novel_lifecycle_id", "content_hash"])
def test_revision_insert_rejects_wrong_scope_or_hash(memory_db, field):
    """ORM 新增历史时拒绝串书、旧生命周期和不一致的正文哈希。"""
    db, _, _, revision = memory_db
    values = {column.key: getattr(revision, column.key) for column in ChapterRevision.__table__.columns if column.key not in {"id", "created_at"}}
    values["version"] = 8
    values[field] = 999 if field == "novel_id" else "wrong"
    db.add(ChapterRevision(**values))
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize("kind", ["job_novel", "job_lifecycle", "digest_chapter"])
def test_derivation_insert_rejects_cross_source_scope(memory_db, kind):
    """简介和任务不能挂到来源之外的作品或章节。"""
    db, novel_id, chapter_id, revision = memory_db
    if kind.startswith("job"):
        item = DerivedJob(novel_id=999 if kind == "job_novel" else novel_id,
                          novel_lifecycle_id="wrong" if kind == "job_lifecycle" else revision.novel_lifecycle_id,
                          source_revision_id=revision.id, recipe_version="scope-v1")
    else:
        item = ChapterDigest(novel_id=novel_id, chapter_id=chapter_id + 1, source_revision_id=revision.id,
                             recipe_version="scope-v1", summary="错误来源")
    db.add(item)
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()


def test_managed_orphan_fails_before_creating_memory_tables(tmp_path):
    """受迁移管理的旧库含孤儿时，在 DDL 前失败，可修复后重试。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'managed-orphan.db'}")
    config = _alembic_config(engine)
    command.upgrade(config, "f7a91b2c340d")
    _seed(engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE chapters SET novel_id = 999"))
    with pytest.raises(MemoryBackfillError, match="novel_id=999"):
        command.upgrade(config, "head")
    assert "chapter_revisions" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f7a91b2c340d"
        connection.execute(text("UPDATE chapters SET novel_id = (SELECT id FROM novels LIMIT 1)"))
    command.upgrade(config, "head")
    assert "chapter_revisions" in inspect(engine).get_table_names()
    engine.dispose()
