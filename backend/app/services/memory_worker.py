"""SQLite 持久任务执行器：固定版本、有界尝试、租约与原子发布。"""

import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from loguru import logger
from sqlalchemy import and_, or_, select, update

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.memory import ChapterDigest, ChapterRevision, DerivedJob, utc_now
from app.models.novel import Chapter, Novel
from app.services.digest_extractor import DigestExtractor, DigestExtractionError, validate_digest
from app.services.memory_config import digest_recipe_version
from app.services.model_result import ModelOutputError


def _snapshot(row):
    return SimpleNamespace(**{column.name: getattr(row, column.name) for column in row.__table__.columns})


def _eligible(now):
    return or_(
        and_(DerivedJob.state == "queued", DerivedJob.available_at <= now),
        and_(DerivedJob.state == "running", or_(DerivedJob.lease_until <= now, DerivedJob.lease_until.is_(None))),
    )


def _source_is_current(db, job, revision):
    if revision is None or revision.novel_id != job.novel_id or revision.novel_lifecycle_id != job.novel_lifecycle_id:
        return False
    novel = db.get(Novel, job.novel_id)
    chapter = db.get(Chapter, revision.chapter_id)
    return bool(
        novel and chapter and novel.rag_lifecycle_id == job.novel_lifecycle_id
        and chapter.novel_id == novel.id
        and chapter.rag_lifecycle_id == revision.chapter_lifecycle_id
        and chapter.version == revision.version and chapter.title == revision.title
        and chapter.chapter_number == revision.chapter_number
        and hashlib.sha256(chapter.content.encode("utf-8")).hexdigest() == revision.content_hash
        and hashlib.sha256(revision.content.encode("utf-8")).hexdigest() == revision.content_hash
    )


class MemoryWorker:
    """模型调用不持有数据库事务，重启后可重新领取到期租约。"""

    def __init__(self, session_factory=SessionLocal, extractor=None):
        self.session_factory = session_factory
        self.extractor = extractor if extractor is not None else DigestExtractor()

    def _claim(self):
        now = utc_now()
        with self.session_factory() as db:
            exhausted = db.execute(update(DerivedJob).where(
                DerivedJob.kind == "chapter_digest", _eligible(now),
                DerivedJob.attempts >= DerivedJob.max_attempts,
            ).values(state="failed", lease_token=None, lease_until=None,
                     error_code="attempts_exhausted", error_message="简介提取已达到最大尝试次数，请手动重建。",
                     updated_at=now)).rowcount
            candidate = db.scalar(select(DerivedJob.id).where(
                DerivedJob.kind == "chapter_digest", _eligible(now),
                DerivedJob.attempts < DerivedJob.max_attempts,
            ).order_by(DerivedJob.available_at, DerivedJob.created_at, DerivedJob.id).limit(1))
            if candidate is None:
                db.commit()
                return None, bool(exhausted)
            token = str(uuid4())
            claimed = db.execute(update(DerivedJob).where(
                DerivedJob.id == candidate, _eligible(now),
                DerivedJob.attempts < DerivedJob.max_attempts,
            ).values(state="running", attempts=DerivedJob.attempts + 1, lease_token=token,
                     lease_until=now + timedelta(seconds=settings.MEMORY_LEASE_SECONDS),
                     error_code=None, error_message=None, updated_at=now)).rowcount
            if not claimed:
                db.commit()
                return None, bool(exhausted)
            job = db.get(DerivedJob, candidate)
            revision = db.get(ChapterRevision, job.source_revision_id)
            if job.recipe_version != digest_recipe_version() or not _source_is_current(db, job, revision):
                job.state = "superseded"
                job.lease_token = job.lease_until = None
                db.commit()
                return None, True
            result = (_snapshot(job), _snapshot(revision))
            db.commit()
            return result, True

    def _acquire_publication(self, db, job):
        """先写 CAS 取得 SQLite 写锁，避免来源检查后被改稿抢先提交。"""
        now = utc_now()
        return db.execute(update(DerivedJob).where(
            DerivedJob.id == job.id, DerivedJob.state == "running",
            DerivedJob.lease_token == job.lease_token, DerivedJob.lease_until > now,
        ).values(updated_at=now)).rowcount == 1

    def _publish(self, job, payload):
        with self.session_factory() as db:
            if not self._acquire_publication(db, job):
                db.rollback()
                return
            current_job = db.get(DerivedJob, job.id)
            revision = db.get(ChapterRevision, current_job.source_revision_id)
            if current_job.recipe_version != digest_recipe_version() or not _source_is_current(db, current_job, revision):
                current_job.state = "superseded"
            else:
                data = validate_digest(payload, revision)
                existing = db.scalar(select(ChapterDigest).where(
                    ChapterDigest.source_revision_id == revision.id,
                    ChapterDigest.recipe_version == current_job.recipe_version,
                ))
                if existing is None:
                    db.add(ChapterDigest(novel_id=revision.novel_id, chapter_id=revision.chapter_id,
                        source_revision_id=revision.id, recipe_version=current_job.recipe_version,
                        status="ready", **data))
                current_job.state = "succeeded"
            current_job.lease_token = current_job.lease_until = None
            current_job.error_code = current_job.error_message = None
            db.commit()

    def _fail(self, job, error):
        if isinstance(error, DigestExtractionError):
            code, message = error.code, str(error)
            retryable = code not in {"source_budget", "invalid_source"}
        elif isinstance(error, ModelOutputError):
            code, message, retryable = error.code, str(error), True
        elif isinstance(error, TimeoutError):
            code, message, retryable = "timeout", "简介提取超时，将在尝试次数允许时重试。", True
        else:
            code, message, retryable = "extraction_failed", "简介提取失败，请检查模型连接后重建。", True
        with self.session_factory() as db:
            if not self._acquire_publication(db, job):
                db.rollback()
                return
            current = db.get(DerivedJob, job.id)
            revision = db.get(ChapterRevision, current.source_revision_id)
            if current.recipe_version != digest_recipe_version() or not _source_is_current(db, current, revision):
                current.state = "superseded"
            else:
                current.state = "queued" if retryable and current.attempts < current.max_attempts else "failed"
                current.available_at = utc_now() + timedelta(seconds=min(60, 2 ** current.attempts))
                current.error_code, current.error_message = code, message
            current.lease_token = current.lease_until = None
            db.commit()

    async def run_once(self) -> bool:
        """处理至多一个任务；返回是否推进了持久状态。"""
        claim, progressed = await asyncio.to_thread(self._claim)
        if claim is None:
            return progressed
        job, revision = claim
        try:
            # 预留发布时间；租约过期后仍由 CAS 拒绝迟到结果。
            timeout = min(settings.LLM_TIMEOUT_SECONDS * (settings.LLM_MAX_RETRIES + 1),
                          max(0.1, settings.MEMORY_LEASE_SECONDS - 1))
            payload = await asyncio.wait_for(self.extractor.extract(revision), timeout=timeout)
            await asyncio.to_thread(self._publish, job, payload)
        except asyncio.CancelledError:
            # 进程关闭保留 running 租约，由下一实例恢复，不能伪报成功。
            raise
        except Exception as exc:
            await asyncio.to_thread(self._fail, job, exc)
        return True

    async def run_forever(self, stop_event: asyncio.Event):
        """串行执行控制并发；数据库临时不可用时退避且不打印敏感异常。"""
        while not stop_event.is_set():
            try:
                progressed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("简介后台任务暂未推进，将稍后重试。")
                progressed = False
            if progressed:
                # 失效任务可能在首次模型 await 前返回，积压清理也须让 HTTP 和停机协程运行。
                await asyncio.sleep(0)
            else:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.MEMORY_POLL_SECONDS)
                except TimeoutError:
                    pass
