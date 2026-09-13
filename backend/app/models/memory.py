"""原文不可变版本、可恢复的派生任务与自动简介。"""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, event, inspect, select
from sqlalchemy.orm import relationship

from app.db.base import Base


def utc_now():
    """SQLite 统一保存无时区 UTC，防止租约比较混用时区。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_memory_id():
    return str(uuid4())


class ChapterRevision(Base):
    """保留期间不能覆盖的作者原文快照。"""
    __tablename__ = "chapter_revisions"
    __table_args__ = (
        UniqueConstraint("chapter_lifecycle_id", "version", name="uq_chapter_revision_version"),
        CheckConstraint("version > 0", name="ck_chapter_revision_version_positive"),
    )
    id = Column(String(36), primary_key=True, default=new_memory_id)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    chapter_lifecycle_id = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False)
    chapter_number = Column(Integer, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(), nullable=False, default=utc_now)

    chapter = relationship("Chapter", back_populates="revisions")
    jobs = relationship("DerivedJob", back_populates="source_revision", cascade="all, delete-orphan")
    digests = relationship("ChapterDigest", back_populates="source_revision", cascade="all, delete-orphan")


class DerivedJob(Base):
    """固定来源版本的持久提取任务，领取和发布由服务使用 CAS。"""
    __tablename__ = "derived_jobs"
    __table_args__ = (
        UniqueConstraint("novel_lifecycle_id", "source_revision_id", "kind", "recipe_version", name="uq_derived_job_recipe"),
        CheckConstraint("state IN ('queued','running','succeeded','failed','cancelled','superseded')", name="ck_derived_job_state"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0", name="ck_derived_job_attempts"),
        Index("ix_derived_jobs_claim", "state", "available_at", "lease_until"),
    )
    id = Column(String(36), primary_key=True, default=new_memory_id)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    source_revision_id = Column(String(36), ForeignKey("chapter_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(40), nullable=False, default="chapter_digest", server_default="chapter_digest")
    recipe_version = Column(String(100), nullable=False)
    state = Column(String(20), nullable=False, default="queued", server_default="queued")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    available_at = Column(DateTime(), nullable=False, default=utc_now)
    lease_token = Column(String(36))
    lease_until = Column(DateTime())
    error_code = Column(String(100))
    error_message = Column(String(500))
    created_at = Column(DateTime(), nullable=False, default=utc_now)
    updated_at = Column(DateTime(), nullable=False, default=utc_now, onupdate=utc_now)

    source_revision = relationship("ChapterRevision", back_populates="jobs")


class ChapterDigest(Base):
    """AI 简介只保存候选变化，不写入作者确认的设定。"""
    __tablename__ = "chapter_digests"
    __table_args__ = (
        UniqueConstraint("source_revision_id", "recipe_version", name="uq_chapter_digest_recipe"),
        CheckConstraint("status IN ('ready','stale')", name="ck_chapter_digest_status"),
    )
    id = Column(String(36), primary_key=True, default=new_memory_id)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False, index=True)
    source_revision_id = Column(String(36), ForeignKey("chapter_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    recipe_version = Column(String(100), nullable=False)
    summary = Column(Text, nullable=False)
    participants = Column(JSON, nullable=False, default=list)
    events = Column(JSON, nullable=False, default=list)
    state_change_candidates = Column(JSON, nullable=False, default=list)
    open_threads = Column(JSON, nullable=False, default=list)
    source_refs = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="ready", server_default="ready")
    created_at = Column(DateTime(), nullable=False, default=utc_now)

    source_revision = relationship("ChapterRevision", back_populates="digests")


@event.listens_for(ChapterRevision, "before_update")
def _reject_revision_overwrite(_mapper, _connection, revision):
    """关系集合变化不影响快照，任何列更新均必须改为创建新版本。"""
    state = inspect(revision)
    if any(state.attrs[column.key].history.has_changes() for column in state.mapper.column_attrs):
        raise ValueError("原文版本不可覆写，请保存为新的章节版本。")


@event.listens_for(ChapterRevision, "before_insert")
def _validate_revision_scope(_mapper, connection, revision):
    """SQLite 外键未开启时也不允许串作品或复用旧生命周期。"""
    from app.models.novel import Chapter, Novel

    source = connection.execute(select(
        Chapter.novel_id, Chapter.rag_lifecycle_id,
        Novel.rag_lifecycle_id.label("novel_lifecycle_id"),
    ).join(Novel, Novel.id == Chapter.novel_id).where(Chapter.id == revision.chapter_id)).first()
    if (source is None or source.novel_id != revision.novel_id
            or source.rag_lifecycle_id != revision.chapter_lifecycle_id
            or source.novel_lifecycle_id != revision.novel_lifecycle_id):
        raise ValueError("原文版本与章节的作品归属或生命周期不一致。")
    if not isinstance(revision.content, str) or sha256(revision.content.encode("utf-8")).hexdigest() != revision.content_hash:
        raise ValueError("原文版本的内容哈希不匹配。")


@event.listens_for(DerivedJob, "before_insert")
@event.listens_for(ChapterDigest, "before_insert")
def _validate_derivation_scope(_mapper, connection, derivation):
    """模型输出中的来源身份不能替代数据库中的真实归属。"""
    source = connection.execute(select(
        ChapterRevision.novel_id, ChapterRevision.chapter_id, ChapterRevision.novel_lifecycle_id,
    ).where(
        ChapterRevision.id == derivation.source_revision_id,
    )).mappings().first()
    if source is None or source["novel_id"] != derivation.novel_id:
        raise ValueError("派生记录与原文版本的作品归属不一致。")
    if isinstance(derivation, DerivedJob) and source["novel_lifecycle_id"] != derivation.novel_lifecycle_id:
        raise ValueError("派生任务与原文版本的作品生命周期不一致。")
    if isinstance(derivation, ChapterDigest) and source["chapter_id"] != derivation.chapter_id:
        raise ValueError("简介与原文版本的章节归属不一致。")
