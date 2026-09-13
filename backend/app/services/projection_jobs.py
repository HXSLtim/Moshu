"""索引任务与作者写入同事务；执行仅使用捕获的不可复用身份。"""
import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, and_, update

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.memory import utc_now
from app.models.novel import Novel, Chapter
from app.models.projection_job import ProjectionJob


def enqueue_projection(db, novel, chapter=None, *, delete=False):
    """不提交事务；清理任务保留身份但不复制作者正文。"""
    db.flush()
    source = 'chapter' if chapter is not None else 'worldview'
    kind = ('delete_chapter' if chapter is not None else 'delete_novel') if delete else source
    lifecycle = chapter.rag_lifecycle_id if chapter is not None else novel.rag_lifecycle_id
    version = 0 if delete else (chapter.version if chapter is not None else novel.rag_revision)
    existing = db.query(ProjectionJob).filter_by(kind=kind, source_lifecycle_id=lifecycle, source_version=version).first()
    if existing:
        return existing
    db.query(ProjectionJob).filter(
        ProjectionJob.source_lifecycle_id == lifecycle,
        ProjectionJob.state.in_(['queued', 'running']),
        ProjectionJob.kind.in_(['chapter', 'worldview']),
    ).update({'state': 'superseded', 'lease_token': None, 'lease_until': None}, synchronize_session=False)
    token = {'_novel_lifecycle': novel.rag_lifecycle_id, '_owner_id': novel.user_id,
             '_source_lifecycle': lifecycle}
    if chapter is not None:
        token['source_key'] = f'novel-{novel.rag_lifecycle_id}-chapter-{lifecycle}'
    job = ProjectionJob(novel_id=novel.id, actor_id=novel.user_id,
                        novel_lifecycle_id=novel.rag_lifecycle_id, source_lifecycle_id=lifecycle,
                        source_version=version, kind=kind,
                        payload={'chapter_id': chapter.id if chapter is not None else None, 'token': token})
    db.add(job)
    db.flush()
    return job


class ProjectionWorker:
    def __init__(self, session_factory=SessionLocal, service=None):
        from app.services.rag_service import rag_service
        self.sessions = session_factory
        self.service = service or rag_service

    def claim(self):
        now = utc_now()
        with self.sessions() as db:
            ready = or_(and_(ProjectionJob.state == 'queued', ProjectionJob.available_at <= now),
                        and_(ProjectionJob.state == 'running', or_(ProjectionJob.lease_until <= now, ProjectionJob.lease_until.is_(None))))
            db.query(ProjectionJob).filter(ready, ProjectionJob.attempts >= ProjectionJob.max_attempts).update(
                {'state': 'failed', 'error': '投影任务尝试次数已耗尽', 'lease_token': None, 'lease_until': None}, synchronize_session=False)
            query = db.query(ProjectionJob).filter(ready, ProjectionJob.attempts < ProjectionJob.max_attempts)
            if not settings.EMBEDDING_ENABLED:
                query = query.filter(ProjectionJob.kind.in_(['delete_chapter', 'delete_novel']))
            row = query.order_by(ProjectionJob.created_at).first()
            if row is None:
                db.commit()
                return None
            token = str(uuid4())
            changed = db.execute(update(ProjectionJob).where(ProjectionJob.id == row.id, ready,
                ProjectionJob.attempts == row.attempts).values(state='running', lease_token=token,
                lease_until=now + timedelta(seconds=settings.PROJECTION_LEASE_SECONDS),
                attempts=ProjectionJob.attempts + 1, error=None)).rowcount
            db.commit()
            if changed != 1:
                return None
            db.refresh(row)
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def load_payload(self, job):
        """每次执行从新 Session 读当前稿；旧来源直接失效，不再调用 Embedding。"""
        if job['kind'].startswith('delete_'):
            return job['payload']
        with self.sessions() as db:
            novel = db.get(Novel, job['novel_id'])
            if (novel is None or novel.user_id != job['actor_id']
                    or novel.rag_lifecycle_id != job['novel_lifecycle_id']):
                return None
            chapter = None
            if job['kind'] == 'chapter':
                chapter = db.get(Chapter, job['payload']['chapter_id'])
                if (chapter is None or chapter.novel_id != novel.id
                        or chapter.rag_lifecycle_id != job['source_lifecycle_id']
                        or chapter.version != job['source_version']):
                    return None
            elif novel.rag_revision != job['source_version']:
                return None
            return {'novel_id': novel.id, 'chapter': chapter.chapter_number if chapter is not None else 0,
                    'content': chapter.content if chapter is not None else novel.worldview or '',
                    'metadata': {**job['payload']['token'], 'source': job['kind'],
                                 'version': job['source_version'], 'chapter_id': chapter.id if chapter is not None else None}}

    def finish(self, job, state, error=None):
        with self.sessions() as db:
            if state == 'queued' and job['attempts'] >= job['max_attempts']:
                state = 'failed'
            result = db.execute(update(ProjectionJob).where(ProjectionJob.id == job['id'],
                ProjectionJob.state == 'running', ProjectionJob.lease_token == job['lease_token'],
                ProjectionJob.lease_until > utc_now()).values(
                state=state, lease_token=None, lease_until=None, error=error,
                available_at=utc_now() + timedelta(seconds=min(60, 2 ** job['attempts']))))
            db.commit()
            return result.rowcount == 1

    async def run_once(self):
        job = await asyncio.to_thread(self.claim)
        if not job:
            return False
        try:
            payload = await asyncio.to_thread(self.load_payload, job)
            if payload is None:
                await asyncio.to_thread(self.finish, job, 'superseded')
                return True
            if job['kind'].startswith('delete_'):
                # 清理与模型无关，异常必须向worker传播，不能把0条与失败混同。
                await asyncio.wait_for(self.service.cleanup_projection_strict(job['kind'], payload['token']),
                                       settings.PROJECTION_OPERATION_SECONDS)
            else:
                result = await asyncio.wait_for(self.service.index_content(**payload), settings.PROJECTION_OPERATION_SECONDS)
                if not result:
                    raise RuntimeError('索引服务暂不可用')
            await asyncio.to_thread(self.finish, job, 'succeeded')
        except asyncio.CancelledError:
            # 不擦除租约；重启后过期重领，重复外部写入由投影身份幂等处理。
            raise
        except Exception:
            await asyncio.to_thread(self.finish, job, 'queued', '投影执行失败，将按有限退避重试')
        return True

    async def run_forever(self, stop):
        from loguru import logger
        while not stop.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception('投影任务领取失败')
                worked = False
            if worked:
                await asyncio.sleep(0)
            else:
                try:
                    await asyncio.wait_for(stop.wait(), settings.PROJECTION_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
