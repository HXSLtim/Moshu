"""持久创作执行器：请求只等待任务，断连不拥有执行协程的生命周期。"""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import wraps
from types import SimpleNamespace
from uuid import uuid4
from threading import Thread, Lock, Event
from concurrent.futures import Future

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.novel import Chapter, Novel
from app.models.writing_chat import WritingGenerationJob, WritingProposal, WritingTurn
from app.services.model.execution import execution_scope
from app.services.conversation.proposals import content_hash

_current_job: ContextVar[str | None] = ContextVar('writing_job_id', default=None)
_running: dict[str, tuple[asyncio.AbstractEventLoop, Future]] = {}
_active = {}
_worker_loop = None
_worker_lock = Lock()
_dispatch_lock = Lock()
_handlers = {}


def _job_model_budget(kind: str, payload: dict) -> int:
    """任务级模型调用上限;嵌套 scope 共享此总额,必须覆盖内层工作流的真实需求。

    chat 是多轮工具循环(路由层 8 次);orchestrate 是规划 1 + 生成至多 6 次;
    高级续写走三角色工作流 5 次;其余为单次调用的显式任务。
    """
    from app.services.generation.orchestrator import MAX_ORCHESTRATION_MODEL_CALLS
    if kind == 'chat':
        return 20  # Agent 多轮工具循环 + 能力工具(编排至多 7 次)嵌套共享
    if kind == 'orchestrate':
        return MAX_ORCHESTRATION_MODEL_CALLS
    if kind in {'continue', 'continue_stream', 'generate'} or payload.get('mode') == 'advanced_continue':
        return 5
    return 1

TERMINAL = {'completed', 'failed', 'cancelled'}


def register_handler(kind, handler):
    _handlers[kind] = handler


def current_job_id():
    return _current_job.get()


def guard_job_publish(db):
    """同事务领取发布权；取消和候选落库通过任务行写锁串行化。"""
    job_id = current_job_id()
    if job_id is not None:
        changed = db.query(WritingGenerationJob).filter_by(id=job_id, status='running').update(
            {'status': 'running'}, synchronize_session=False)
        if not changed:
            raise HTTPException(409, '任务已停止或已过期，不能发布候选')
        deadline = db.execute(select(WritingGenerationJob.deadline_at).where(WritingGenerationJob.id == job_id)).scalar_one()
        if datetime.utcnow() >= deadline:
            raise TimeoutError('任务截止时间已到，不能发布候选')
    return job_id


def _scope(db, novel_id, actor_id, lifecycle):
    novel = db.get(Novel, novel_id, populate_existing=True)
    if novel is None or novel.user_id != actor_id or novel.rag_lifecycle_id != lifecycle:
        raise HTTPException(404, '作品不存在、无权访问或来源已改变')
    return novel


def owned_job(db, job_id, novel_id, actor_id):
    job = db.get(WritingGenerationJob, str(job_id), populate_existing=True)
    if job is None or job.novel_id != novel_id or job.actor_id != actor_id:
        raise HTTPException(404, '创作任务不存在或无权访问')
    _scope(db, novel_id, actor_id, job.novel_lifecycle_id)
    return job


def _cancel_outputs(db, job):
    db.query(WritingProposal).filter_by(execution_job_id=job.id, status='pending').update(
        {'status': 'cancelled'}, synchronize_session=False)
    if job.kind == 'chat':
        db.query(WritingTurn).filter_by(novel_id=job.novel_id, request_id=job.payload['request_id'], status='pending').update(
            {'status': 'cancelled' if job.status == 'cancelled' else 'failed', 'error': job.error}, synchronize_session=False)


def reconcile_jobs(db):
    """过期租约明确失败；没有自动重放有费用的模型请求。"""
    expired = db.query(WritingGenerationJob).filter(
        WritingGenerationJob.status.in_(['queued', 'running']),
        WritingGenerationJob.deadline_at < datetime.utcnow()).all()
    for job in expired:
        changed = db.query(WritingGenerationJob).filter(
            WritingGenerationJob.id == job.id, WritingGenerationJob.status.in_(['queued', 'running'])).update(
            {'status': 'failed', 'error': '上次执行已中断或超过截止时间，请显式重试。',
             'error_code': 'execution_expired', 'finished_at': datetime.utcnow()}, synchronize_session=False)
        if changed:
            db.refresh(job)
            _cancel_outputs(db, job)
    db.commit()
    return len(expired)


def submit_job(db, *, novel_id, actor_id, lifecycle, request_id, kind, payload, source_scope=None):
    _scope(db, novel_id, actor_id, lifecycle)
    old = db.query(WritingGenerationJob).filter_by(novel_lifecycle_id=lifecycle, request_id=str(request_id)).first()
    if old:
        if old.actor_id != actor_id or old.kind != kind or old.payload != payload:
            raise HTTPException(409, '请求标识已用于不同的创作任务')
        return old
    if source_scope is None:
        source_scope = {}
        chapter_id = payload.get('chapter_id') or payload.get('base_chapter_id')
        creates_chapter = kind == 'auto_chapter' or (kind == 'chat' and payload.get('mode') == 'new_chapter')
        if creates_chapter:
            from app.crud import novel as novel_crud
            source_scope['target_chapter_number'] = novel_crud.get_max_chapter_number(db, novel_id) + 1
            if kind == 'auto_chapter' and chapter_id is None:
                latest = novel_crud.get_latest_chapter(db, novel_id)
                chapter_id = latest.id if latest else None
        if chapter_id:
            chapter = db.get(Chapter, chapter_id)
            if chapter is None or chapter.novel_id != novel_id:
                raise HTTPException(404, '章节不存在或不属于本书')
            expected = payload.get('expected_chapter_lifecycle_id')
            if expected and expected != chapter.rag_lifecycle_id:
                raise HTTPException(409, '章节来源已经改变')
            source_scope.update(chapter_id=chapter.id, chapter_lifecycle_id=chapter.rag_lifecycle_id,
                base_version=chapter.version, chapter_title=chapter.title,
                chapter_number=chapter.chapter_number, base_content_hash=content_hash(chapter.content))
    _validate_chapter_scope(db, novel_id, source_scope)
    now = datetime.utcnow()
    timeout = settings.LLM_TIMEOUT_SECONDS * (settings.LLM_MAX_RETRIES + 1)
    job = WritingGenerationJob(id=str(uuid4()), request_id=str(request_id), novel_id=novel_id,
        actor_id=actor_id, novel_lifecycle_id=lifecycle, kind=kind, payload=payload,
        source_scope=source_scope, status='queued', deadline_at=now + timedelta(seconds=timeout + 30))
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        old = db.query(WritingGenerationJob).filter_by(novel_lifecycle_id=lifecycle, request_id=str(request_id)).one()
        if old.actor_id != actor_id or old.kind != kind or old.payload != payload:
            raise HTTPException(409, '请求标识已用于不同的创作任务')
        return old
    db.refresh(job)
    return job


def _validate_chapter_scope(db, novel_id, scope):
    if scope.get('chapter_id'):
        chapter = db.get(Chapter, scope['chapter_id'], populate_existing=True)
        if (chapter is None or chapter.novel_id != novel_id
                or chapter.rag_lifecycle_id != scope['chapter_lifecycle_id']
                or chapter.version != scope['base_version']
                or ('base_content_hash' in scope and content_hash(chapter.content) != scope['base_content_hash'])
                or ('chapter_number' in scope and chapter.chapter_number != scope['chapter_number'])):
            raise HTTPException(409, '任务引用的原文版本或章节生命周期已经改变，请重新发起任务')
    if 'target_chapter_number' in scope:
        from app.crud import novel as novel_crud
        if novel_crud.get_max_chapter_number(db, novel_id) + 1 != scope['target_chapter_number']:
            raise HTTPException(409, '任务引用的新章位置已经改变，请重新发起任务')


def _execution_loop():
    """模型客户端固定在同一后台事件循环，数据库锁等待不阻塞HTTP循环。"""
    global _worker_loop
    with _worker_lock:
        if _worker_loop is None:
            ready = Event()
            def run():
                global _worker_loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _worker_loop = loop
                ready.set()
                loop.run_forever()
            Thread(target=run, name='writing-executor', daemon=True).start()
            ready.wait()
        return _worker_loop


async def _run_tracked(sessions, job_id):
    task = asyncio.current_task()
    _active[job_id] = task
    try:
        await _run_job(sessions, job_id)
    finally:
        _active.pop(job_id, None)


def dispatch_job(bind, job_id):
    created = False
    with _dispatch_lock:
        existing = _running.get(job_id)
        if existing:
            future = existing[1]
        else:
            loop = _execution_loop()
            future = asyncio.run_coroutine_threadsafe(_run_tracked(sessionmaker(bind=bind), job_id), loop)
            _running[job_id] = (loop, future)
            created = True
    if created:
        def remove(completed):
            with _dispatch_lock:
                current = _running.get(job_id)
                if current and current[1] is completed:
                    _running.pop(job_id, None)
        future.add_done_callback(remove)
    try:
        return asyncio.wrap_future(future, loop=asyncio.get_running_loop())
    except RuntimeError:
        return future


async def _run_job(sessions, job_id):
    meter = None
    token = _current_job.set(job_id)
    try:
        with sessions() as db:
            claimed = db.query(WritingGenerationJob).filter_by(id=job_id, status='queued').update(
                {'status': 'running', 'started_at': datetime.utcnow()}, synchronize_session=False)
            db.commit()
            if not claimed:
                return
            job = db.get(WritingGenerationJob, job_id)
            _scope(db, job.novel_id, job.actor_id, job.novel_lifecycle_id)
            _validate_chapter_scope(db, job.novel_id, job.source_scope or {})
            payload, kind, actor_id, novel_id = job.payload, job.kind, job.actor_id, job.novel_id
            remaining = max(0.01, (job.deadline_at - datetime.utcnow()).total_seconds())
            db.commit()
            async with execution_scope(max_model_calls=_job_model_budget(kind, payload),
                                       timeout_seconds=remaining, execution_id=job_id) as meter:
                result = await _handlers[kind](payload, novel_id, SimpleNamespace(id=actor_id), db)
                from fastapi.responses import StreamingResponse
                if isinstance(result, StreamingResponse):
                    import json
                    events = []
                    async for chunk in result.body_iterator:
                        if isinstance(chunk, bytes):
                            chunk = chunk.decode('utf-8')
                        for line in chunk.splitlines():
                            if line.startswith('data: '):
                                event = json.loads(line[6:])
                                if event.get('type') == 'error':
                                    raise HTTPException(500, '流式创作任务未能完成')
                                events.append(event)
                        guard_job_publish(db)
                        db.query(WritingGenerationJob).filter_by(id=job_id, status='running').update(
                            {'result': {'events': list(events)}}, synchronize_session=False)
                        db.commit()
                    result = {'events': events}
            result = jsonable_encoder(result)
            if isinstance(result, dict):
                result['execution'] = meter.snapshot()
            guard_job_publish(db)
            job = db.get(WritingGenerationJob, job_id, populate_existing=True)
            _scope(db, novel_id, actor_id, job.novel_lifecycle_id)
            output_status = result.get('status') if isinstance(result, dict) and kind == 'chat' else None
            job.status = output_status if output_status in {'failed', 'cancelled'} else 'completed'
            job.result = result
            job.execution = meter.snapshot()
            job.error = result.get('error') if output_status in {'failed', 'cancelled'} else None
            job.error_code = meter.error_code if output_status in {'failed', 'cancelled'} else None
            job.finished_at = datetime.utcnow()
            db.query(WritingProposal).filter_by(execution_job_id=job_id).update({'execution': meter.snapshot()}, synchronize_session=False)
            if kind == 'chat':
                db.query(WritingTurn).filter_by(novel_id=novel_id, request_id=payload['request_id']).update(
                    {'execution': meter.snapshot()}, synchronize_session=False)
            db.commit()
            auto_apply_needed = job.status == 'completed'
        # 钩子在主 Session 关闭后执行(采纳命令校验任务终态),独立会话避免与
        # 主连接并发;尽力而为,任何异常都不改变任务终态,候选保留待作者确认。
        if auto_apply_needed:
            from loguru import logger as _logger
            try:
                from app.services.conversation.proposals import auto_apply_pending
                bind = sessions.kw.get('bind') or sessions().get_bind()
                await asyncio.to_thread(auto_apply_pending, bind, novel_id, actor_id, job_id)
            except BaseException as hook_exc:  # noqa: BLE001
                _logger.warning('审核模式自动采纳钩子未执行完成,候选保留待确认: {}', hook_exc)
    except BaseException as exc:
        with sessions() as db:
            job = db.get(WritingGenerationJob, job_id)
            if job is not None:
                cancelled = isinstance(exc, asyncio.CancelledError)
                code = ('cancelled' if cancelled else 'deadline_exceeded' if isinstance(exc, TimeoutError)
                        else meter.error_code if meter and meter.error_code else
                        f'http_{exc.status_code}' if isinstance(exc, HTTPException) else getattr(exc, 'code', None) or 'execution_failed')
                message = '已停止生成' if cancelled else ('本轮执行超时，请缩小任务后重试。' if isinstance(exc, TimeoutError)
                    else exc.detail if isinstance(exc, HTTPException) and exc.status_code < 500
                    else '创作任务未完成，请检查模型连接或任务要求后重试。')
                changed = db.query(WritingGenerationJob).filter(
                    WritingGenerationJob.id == job_id, WritingGenerationJob.status.in_(['queued', 'running'])).update(
                    {'status': 'cancelled' if cancelled else 'failed', 'error': str(message)[:300], 'error_code': code,
                     'execution': meter.snapshot() if meter else None, 'finished_at': datetime.utcnow()}, synchronize_session=False)
                if changed:
                    db.refresh(job)
                    _cancel_outputs(db, job)
                elif meter:
                    if job.status == 'cancelled':
                        meter.status = 'cancelled'
                        meter.error_code = 'cancelled'
                    db.query(WritingGenerationJob).filter_by(id=job_id, status='cancelled').update({'execution': meter.snapshot()})
                db.commit()
        if not isinstance(exc, (Exception, asyncio.CancelledError)):
            raise
    finally:
        _current_job.reset(token)


def _cancel_execution(job_id):
    task = _active.get(job_id)
    if task is not None:
        task.cancel()


def stop_job(db, job):
    changed = db.query(WritingGenerationJob).filter(
        WritingGenerationJob.id == job.id, WritingGenerationJob.status.in_(['queued', 'running'])).update(
        {'status': 'cancelled', 'error': '已停止生成', 'error_code': 'cancelled', 'finished_at': datetime.utcnow()}, synchronize_session=False)
    if changed:
        db.refresh(job)
        _cancel_outputs(db, job)
        db.commit()
        running = _running.get(job.id)
        if running:
            running[0].call_soon_threadsafe(_cancel_execution, job.id)
    db.refresh(job)
    return job


async def shutdown_writing_jobs():
    if _worker_loop is None:
        return
    async def drain():
        tasks = list(_active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(drain(), _worker_loop))


def submit_legacy_job(bind, *, novel_id, actor_id, kind, payload):
    """请求只跨线程传标量与Engine，Session在线程内创建并关闭。"""
    with sessionmaker(bind=bind)() as db:
        novel = db.get(Novel, novel_id)
        if novel is None or novel.user_id != actor_id:
            raise HTTPException(404, '小说不存在或无权访问')
        expected = payload.get('expected_novel_lifecycle_id')
        if expected and expected != novel.rag_lifecycle_id:
            raise HTTPException(409, '小说来源已变化')
        job = submit_job(db, novel_id=novel_id, actor_id=actor_id, lifecycle=novel.rag_lifecycle_id,
            request_id=payload.get('request_id') or str(uuid4()), kind=kind, payload=payload)
        return job.id


def read_legacy_result(bind, job_id, novel_id, actor_id):
    with sessionmaker(bind=bind)() as db:
        job = owned_job(db, job_id, novel_id, actor_id)
        if job.result is not None:
            return job.result
        response_status = int(job.error_code[5:]) if job.error_code and job.error_code.startswith('http_') else 409 if job.status == 'cancelled' else 500
        raise HTTPException(response_status, job.error or '任务尚未完成')


def durable_route(kind):
    """旧 HTTP 契约继续等待，但执行使用独立 Session 和可查询的持久行。"""
    def decorate(handler):
        @wraps(handler)
        async def wrapped(*args, **kwargs):
            if current_job_id() is not None:
                return await handler(*args, **kwargs)
            from inspect import signature
            arguments = signature(handler).bind(*args, **kwargs).arguments
            db = arguments['db']
            user = arguments.get('current_user') or arguments.get('user')
            request = arguments.get('request') or arguments.get('data')
            novel_id = arguments.get('novel_id') or request.novel_id
            bind, actor_id = db.get_bind(), user.id
            job_id = await asyncio.to_thread(submit_legacy_job, bind, novel_id=novel_id,
                actor_id=actor_id, kind=kind, payload=request.model_dump(mode='json'))
            await asyncio.shield(dispatch_job(bind, job_id))
            return await asyncio.to_thread(read_legacy_result, bind, job_id, novel_id, actor_id)

        return wrapped
    return decorate


async def run_recovery(stop_event, session_factory=None):
    """独立线程和独立Session收敛过期任务；不自动重复有费用的模型调用。"""
    if session_factory is None:
        from app.db.base import SessionLocal
        session_factory = SessionLocal
    def reconcile():
        with session_factory() as db:
            reconcile_jobs(db)
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(reconcile)
        except Exception as exc:
            from loguru import logger
            logger.error('创作任务恢复检查失败：{}', type(exc).__name__)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=10)
        except TimeoutError:
            pass
