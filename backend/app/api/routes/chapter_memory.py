"""受作者权限与来源生命周期约束的原文历史、简介和提取任务 API。"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.base import get_db
from app.models.memory import ChapterDigest, ChapterRevision, DerivedJob, utc_now
from app.models.novel import Chapter, Novel
from app.models.user import User
from app.services.chapter_memory import ensure_digest_job, ensure_revision
from app.services.context_budget import ensure_digest_source_budget
from app.services.memory_config import digest_recipe_version

router = APIRouter()


def owned_novel(db: Session, novel_id: int, user: User) -> Novel:
    novel = db.get(Novel, novel_id)
    if novel is None or novel.user_id != user.id:
        raise HTTPException(404, "小说不存在或无权访问")
    return novel


def owned_chapter(db, novel_id, chapter_id, user):
    novel = owned_novel(db, novel_id, user)
    chapter = db.get(Chapter, chapter_id)
    if chapter is None or chapter.novel_id != novel.id:
        raise HTTPException(404, "章节不存在或无权访问")
    return novel, chapter


def revision_query(db, novel, chapter):
    return db.query(ChapterRevision).filter_by(
        novel_id=novel.id, chapter_id=chapter.id,
        novel_lifecycle_id=novel.rag_lifecycle_id,
        chapter_lifecycle_id=chapter.rag_lifecycle_id,
    )


def job_response(job):
    return {field: getattr(job, field) for field in (
        "id", "state", "attempts", "max_attempts", "error_code", "error_message",
    )}


def revision_response(revision, *, include_content=False):
    result = {field: getattr(revision, field) for field in (
        "id", "version", "chapter_number", "title", "content_hash", "created_at",
    )}
    if include_content:
        result.update(content=revision.content, chapter_id=revision.chapter_id)
    return result


@router.get("/novels/{novel_id}/chapters/{chapter_id}/revisions")
def list_revisions(novel_id: int, chapter_id: int,
                   limit: int = Query(20, ge=1, le=100),
                   before_version: int | None = Query(None, gt=0),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    novel, chapter = owned_chapter(db, novel_id, chapter_id, user)
    query = revision_query(db, novel, chapter)
    if before_version is not None:
        query = query.filter(ChapterRevision.version < before_version)
    return [revision_response(revision) for revision in query.order_by(ChapterRevision.version.desc()).limit(limit)]


@router.get("/novels/{novel_id}/revisions/{revision_id}")
def get_revision(novel_id: int, revision_id: UUID,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    novel = owned_novel(db, novel_id, user)
    revision = db.get(ChapterRevision, str(revision_id))
    if revision is None or revision.novel_id != novel.id or revision.novel_lifecycle_id != novel.rag_lifecycle_id:
        raise HTTPException(404, "原文版本不存在或无权访问")
    chapter = db.get(Chapter, revision.chapter_id)
    if chapter is None or chapter.novel_id != novel.id or chapter.rag_lifecycle_id != revision.chapter_lifecycle_id:
        raise HTTPException(404, "原文版本不属于当前章节")
    return revision_response(revision, include_content=True)


@router.get("/novels/{novel_id}/chapters/{chapter_id}/digest")
def get_digest(novel_id: int, chapter_id: int,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    novel, chapter = owned_chapter(db, novel_id, chapter_id, user)
    revisions = revision_query(db, novel, chapter)
    recipe = digest_recipe_version()
    pair = db.query(ChapterDigest, ChapterRevision).join(
        ChapterRevision, ChapterDigest.source_revision_id == ChapterRevision.id,
    ).filter(
        ChapterRevision.id.in_(revisions.with_entities(ChapterRevision.id)),
        ChapterDigest.novel_id == novel.id, ChapterDigest.chapter_id == chapter.id,
    ).order_by(ChapterRevision.version.desc(), ChapterDigest.created_at.desc()).first()
    # 同版本更换配方后，优先显示当前配方，不能由另一配方的创建时间遮挡。
    exact = db.query(ChapterDigest, ChapterRevision).join(
        ChapterRevision, ChapterDigest.source_revision_id == ChapterRevision.id,
    ).filter(
        ChapterRevision.id.in_(revisions.with_entities(ChapterRevision.id)),
        ChapterRevision.version == chapter.version, ChapterDigest.recipe_version == recipe,
        ChapterDigest.novel_id == novel.id, ChapterDigest.chapter_id == chapter.id,
    ).first()
    pair = exact or pair
    digest = None
    status = "missing"
    if pair:
        record, source = pair
        status = "ready" if (record.status == "ready" and source.version == chapter.version
                             and record.recipe_version == recipe) else "stale"
        digest = {field: getattr(record, field) for field in (
            "id", "source_revision_id", "summary", "participants", "events",
            "state_change_candidates", "open_threads", "source_refs", "created_at",
        )}
        digest["source_version"] = source.version
    revision = revisions.filter_by(version=chapter.version).first()
    job = None if revision is None else db.query(DerivedJob).filter_by(
        source_revision_id=revision.id, novel_lifecycle_id=novel.rag_lifecycle_id,
        kind="chapter_digest", recipe_version=recipe,
    ).first()
    return {"status": status, "current_version": chapter.version,
            "worker_enabled": settings.MEMORY_WORKER_ENABLED, "digest": digest,
            "job": job_response(job) if job else None}


@router.post("/novels/{novel_id}/chapters/{chapter_id}/digest/rebuild", status_code=202)
def rebuild_digest(novel_id: int, chapter_id: int,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    novel, chapter = owned_chapter(db, novel_id, chapter_id, user)
    try:
        # 无副作用的条件 UPDATE 串行化保存与重建，避免检查后新稿已变化。
        locked = db.execute(text(
            "UPDATE chapters SET version=version WHERE id=:id AND novel_id=:novel_id "
            "AND rag_lifecycle_id=:lifecycle AND version=:version"
        ), {"id": chapter.id, "novel_id": novel.id, "lifecycle": chapter.rag_lifecycle_id,
            "version": chapter.version})
        if locked.rowcount != 1:
            raise HTTPException(409, "章节已变化，请刷新后重建简介")
        db.refresh(chapter)
        try:
            ensure_digest_source_budget(chapter.content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        revision = ensure_revision(db, chapter)
        job = ensure_digest_job(db, revision)
        if job.state in {"failed", "cancelled", "superseded"}:
            job.state, job.attempts, job.available_at = "queued", 0, utc_now()
            job.lease_token = job.lease_until = None
            job.error_code = job.error_message = None
        db.commit()
        db.refresh(job)
        return job_response(job)
    except Exception:
        db.rollback()
        raise


@router.get("/memory-jobs/{job_id}")
def get_job(job_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(DerivedJob, str(job_id))
    if job is None:
        raise HTTPException(404, "提取任务不存在或无权访问")
    novel = owned_novel(db, job.novel_id, user)
    revision = db.get(ChapterRevision, job.source_revision_id)
    if (job.novel_lifecycle_id != novel.rag_lifecycle_id or revision is None
            or revision.novel_id != novel.id or revision.novel_lifecycle_id != novel.rag_lifecycle_id):
        raise HTTPException(404, "提取任务来源已失效")
    chapter = db.get(Chapter, revision.chapter_id)
    if chapter is None or chapter.novel_id != novel.id or chapter.rag_lifecycle_id != revision.chapter_lifecycle_id:
        raise HTTPException(404, "提取任务来源已失效")
    return job_response(job)


class RestoreRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)
    expected_chapter_lifecycle_id: str = Field(min_length=32, max_length=32)
    expected_novel_lifecycle_id: str = Field(min_length=32, max_length=32)


@router.post("/novels/{novel_id}/revisions/{revision_id}/restore")
def restore_revision(novel_id: int, revision_id: UUID, data: RestoreRevisionInput,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """恢复通过新增版本表达，绝不覆盖原文历史，也不复用旧简介。"""
    from app.crud.novel import update_chapter, ChapterVersionConflictError
    from app.models.schemas import ChapterUpdate, ChapterResponse
    source = get_revision(novel_id, revision_id, db, user)
    novel, chapter = owned_chapter(db, novel_id, source["chapter_id"], user)
    try:
        restored = update_chapter(db, chapter.id, ChapterUpdate(
            expected_version=data.expected_version,
            expected_novel_lifecycle_id=data.expected_novel_lifecycle_id,
            expected_chapter_lifecycle_id=data.expected_chapter_lifecycle_id,
            title=source["title"], content=source["content"],
        ))
    except ChapterVersionConflictError as exc:
        raise HTTPException(409, "当前章节已变化，请核对后再恢复") from exc
    return ChapterResponse.model_validate(restored)


@router.post("/memory-jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """取消只改变仍在执行或排队的任务，迟到提取不能发布。"""
    get_job(job_id, db, user)
    db.query(DerivedJob).filter(DerivedJob.id == str(job_id), DerivedJob.state.in_(["queued", "running"])).update(
        {"state": "cancelled", "lease_token": None, "lease_until": None,
         "error_code": "author_cancelled", "error_message": "作者已取消提取", "updated_at": utc_now()},
        synchronize_session=False,
    )
    db.commit()
    return job_response(db.get(DerivedJob, str(job_id)))
