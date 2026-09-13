"""章节事务内的原文快照与派生任务；此模块从不提交事务。"""
import hashlib

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.memory import ChapterDigest, ChapterRevision, DerivedJob
from app.models.novel import Chapter, Novel
from app.services.memory_config import digest_recipe_version


def ensure_revision(db: Session, chapter: Chapter) -> ChapterRevision:
    """仅复制已保存版本；调用方必须持有对应章节写入事务。"""
    db.flush()
    novel = db.get(Novel, chapter.novel_id)
    if novel is None:
        raise ValueError("章节缺少所属小说，无法保存原文版本")
    revision = db.query(ChapterRevision).filter_by(
        chapter_lifecycle_id=chapter.rag_lifecycle_id, version=chapter.version,
    ).first()
    content_hash = hashlib.sha256(chapter.content.encode("utf-8")).hexdigest()
    if revision:
        if (revision.content_hash != content_hash or revision.content != chapter.content
                or revision.title != chapter.title or revision.chapter_number != chapter.chapter_number
                or revision.novel_lifecycle_id != novel.rag_lifecycle_id):
            raise ValueError("原文版本与当前章节不一致，不能覆盖已有历史")
        return revision
    revision = ChapterRevision(
        novel_id=novel.id, chapter_id=chapter.id,
        novel_lifecycle_id=novel.rag_lifecycle_id,
        chapter_lifecycle_id=chapter.rag_lifecycle_id, version=chapter.version,
        chapter_number=chapter.chapter_number, title=chapter.title,
        content=chapter.content, content_hash=content_hash,
    )
    db.add(revision)
    db.flush()
    return revision


def ensure_digest_job(db: Session, revision: ChapterRevision) -> DerivedJob:
    """同来源与配方复用任务；失败后的手动重试由专用命令处理。"""
    recipe = digest_recipe_version()
    job = db.query(DerivedJob).filter_by(
        novel_lifecycle_id=revision.novel_lifecycle_id,
        source_revision_id=revision.id, kind="chapter_digest", recipe_version=recipe,
    ).first()
    if job:
        return job
    job = DerivedJob(
        novel_id=revision.novel_id, novel_lifecycle_id=revision.novel_lifecycle_id,
        source_revision_id=revision.id, kind="chapter_digest", recipe_version=recipe,
        max_attempts=settings.MEMORY_MAX_ATTEMPTS,
    )
    db.add(job)
    db.flush()
    return job


def record_chapter_save(db: Session, chapter: Chapter) -> ChapterRevision:
    """正文保存、版本、任务和旧记忆失效组成一个不可拆分的事务。"""
    revision = ensure_revision(db, chapter)
    from app.services.story_memory import invalidate_chapter_sources
    invalidate_chapter_sources(db, chapter)
    from app.services.projection_jobs import enqueue_projection
    enqueue_projection(db, db.get(Novel, chapter.novel_id), chapter)
    old_revisions = db.query(ChapterRevision.id).filter(
        ChapterRevision.chapter_lifecycle_id == chapter.rag_lifecycle_id,
        ChapterRevision.id != revision.id,
    )
    db.query(ChapterDigest).filter(ChapterDigest.source_revision_id.in_(old_revisions)).update(
        {"status": "stale"}, synchronize_session=False,
    )
    db.query(DerivedJob).filter(
        DerivedJob.source_revision_id.in_(old_revisions),
        DerivedJob.state.in_(["queued", "running"]),
    ).update({"state": "superseded", "lease_token": None, "lease_until": None}, synchronize_session=False)
    if chapter.content.strip():
        ensure_digest_job(db, revision)
    return revision
