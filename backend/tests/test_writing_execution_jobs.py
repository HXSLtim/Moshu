"""真实SQLite验证创作执行与候选采纳边界。"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from threading import Event, get_ident
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.api.routes import writing_chat
from app.db.base import Base
from app.models.memory import ChapterRevision, DerivedJob
from app.models.novel import Chapter, Novel
from app.models.user import User
from tests.agent_stub import AgentStub
from app.models.writing_chat import WritingAdoption, WritingGenerationJob, WritingProposal, WritingTurn
from app.models.story_memory import StoryMemoryHead
from app.services.conversation import jobs as writing_jobs
from app.services.model.execution import ExecutionBudgetError, execution_scope, invoke_model
from app.services.conversation.proposals import create_proposal, decide_proposal
from app.services.context.builder import ContextScopeError
from app.services.conversation.tasks import TaskOptions, execute_task
from app.services.model.result import ModelOutputError

@pytest.fixture
def job_db(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'jobs.db'), connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([User(id=1, username='one', email='one@test.example', hashed_password='x'),
                    User(id=2, username='two', email='two@test.example', hashed_password='x')]); db.commit()
        db.add(Novel(id=1, user_id=1, title='创作任务测试')); db.commit()
        db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='原文中的灯亮了。')); db.commit()
    yield sessions
    engine.dispose()

def submit(sessions, **changes):
    with sessions() as db:
        request_id = str(uuid4())
        args = dict(novel_id=1, actor_id=1, lifecycle=db.get(Novel, 1).rag_lifecycle_id,
            request_id=request_id, kind='chat', payload={'request_id': request_id, 'chapter_id': 1,
            'mode': 'continue', 'message': '继续写灯下的人', 'current_content': '原文中的灯亮了。'})
        args.update(changes)
        return writing_jobs.submit_job(db, **args).id

@pytest.mark.asyncio
async def test_http_disconnect_keeps_execution_and_proposal(job_db, monkeypatch):
    """取消HTTP等待者后，独立Session中的任务继续完成。"""
    entered, release = Event(), Event()
    async def model(_):
        entered.set(); await asyncio.to_thread(release.wait)
        return SimpleNamespace(content='他推开窗，看见风中一盏红灯。', usage_metadata={'input_tokens': 7, 'output_tokens': 9, 'total_tokens': 16})
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    with job_db() as request_db:
        data = writing_chat.TurnCreate(request_id=uuid4(), chapter_id=1, mode='continue', message='续写', current_content='原文中的灯亮了。')
        waiter = asyncio.create_task(writing_chat.send_turn(novel_id=1, data=data, db=request_db, user=SimpleNamespace(id=1)))
        await asyncio.to_thread(entered.wait); waiter.cancel()
        with pytest.raises(asyncio.CancelledError): await waiter
    release.set()
    await asyncio.wrap_future(list(writing_jobs._running.values())[0][1])
    with job_db() as db:
        job = db.query(WritingGenerationJob).one()
        assert job.status == 'completed'
        assert job.execution['usage']['total_tokens'] == 16
        assert job.execution['execution_id'] == job.id
        assert db.query(WritingProposal).one().status == 'pending'
        assert db.get(Chapter, 1).content == '原文中的灯亮了。'

@pytest.mark.asyncio
async def test_cancel_rejects_model_that_swallows_cancellation(job_db, monkeypatch):
    entered = Event()
    async def model(_):
        entered.set()
        try: await asyncio.Event().wait()
        except asyncio.CancelledError: return SimpleNamespace(content='迟到正文')
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    job_id = submit(job_db)
    task = writing_jobs.dispatch_job(job_db.kw['bind'], job_id)
    await asyncio.to_thread(entered.wait)
    with job_db() as db: writing_jobs.stop_job(db, writing_jobs.owned_job(db, job_id, 1, 1))
    await task
    with job_db() as db:
        assert db.get(WritingGenerationJob, job_id).status == 'cancelled'
        assert db.query(WritingProposal).count() == 0
        assert db.query(WritingTurn).one().status == 'cancelled'

@pytest.mark.asyncio
async def test_two_claims_make_one_model_call(job_db, monkeypatch):
    model = AsyncMock(return_value=SimpleNamespace(content='完整正文'))
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    job_id = submit(job_db)
    await asyncio.gather(writing_jobs._run_job(job_db, job_id), writing_jobs._run_job(job_db, job_id))
    assert model.await_count == 1
    with job_db() as db: assert db.query(WritingProposal).count() == 1

@pytest.mark.asyncio
async def test_frozen_scope_rejects_reused_chapter(job_db, monkeypatch):
    model = AsyncMock(return_value=SimpleNamespace(content='不应生成'))
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    job_id = submit(job_db)
    with job_db() as db:
        db.get(Chapter, 1).rag_lifecycle_id = uuid4().hex; db.commit()
    await writing_jobs._run_job(job_db, job_id)
    with job_db() as db:
        assert db.get(WritingGenerationJob, job_id).status == 'failed'
        assert db.query(WritingProposal).count() == 0
    model.assert_not_awaited()

def test_restart_expiry_and_retry_preserve_source(job_db):
    job_id = submit(job_db)
    with job_db() as db:
        job = db.get(WritingGenerationJob, job_id)
        job.status = 'running'; job.deadline_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
        assert writing_jobs.reconcile_jobs(db) == 1
        db.refresh(job)
        assert job.status == 'failed' and job.error_code == 'execution_expired'
        original = dict(job.source_scope)
        db.get(Chapter, 1).version += 1; db.commit()
        with pytest.raises(HTTPException) as exc:
            writing_jobs.submit_job(db, novel_id=1, actor_id=1, lifecycle=job.novel_lifecycle_id,
                request_id=str(uuid4()), kind=job.kind, payload=job.payload, source_scope=original)
        assert exc.value.status_code == 409

def proposal(job_db):
    with job_db() as db:
        chapter = db.get(Chapter, 1)
        item = create_proposal(db, novel=db.get(Novel, 1), actor_id=1, chapter=chapter,
            base_content=chapter.content, operation='append', content='候选正文')
        db.commit(); return item.id


def test_proposal_rejects_late_memory_snapshot(job_db):
    """结构化记忆在模型等待期间更新后，旧上下文不能落为可采纳候选。"""
    with job_db() as db:
        novel = db.get(Novel, 1)
        db.add(StoryMemoryHead(novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id, version=2))
        db.commit()
        chapter = db.get(Chapter, 1)
        db.query(StoryMemoryHead).filter_by(novel_id=novel.id).update({"version": 3})
        db.commit()
        with pytest.raises(ContextScopeError, match="结构化记忆已更新"):
            create_proposal(db, novel=novel, actor_id=1, chapter=chapter,
                base_content=chapter.content, operation='append', content='旧上下文候选',
                context_manifest={"scope": {"memory_head_version": 2}})

def accept(db, proposal_id, request_id=None, **changes):
    item = db.get(WritingProposal, proposal_id)
    args = dict(novel_id=1, proposal_id=proposal_id, actor_id=1, decision='accept', request_id=request_id or str(uuid4()),
                expected_version=item.base_version, expected_content_hash=item.base_content_hash)
    args.update(changes); return decide_proposal(db, **args)

def test_adoption_saves_revision_job_and_idempotent_audit(job_db):
    proposal_id = proposal(job_db); request_id = str(uuid4())
    with job_db() as db:
        first = accept(db, proposal_id, request_id, candidate_content='作者修改的候选')
        again = accept(db, proposal_id, request_id, candidate_content='作者修改的候选')
        assert first['chapter'] == again['chapter']
        assert db.query(WritingAdoption).count() == db.query(ChapterRevision).count() == db.query(DerivedJob).count() == 1
        assert db.get(Chapter, 1).content.endswith('作者修改的候选')
        with pytest.raises(HTTPException) as exc: accept(db, proposal_id, request_id, candidate_content='篡改重传')
        assert exc.value.status_code == 409

def test_audit_failure_rolls_back_all_outputs(job_db):
    proposal_id = proposal(job_db)
    def reject_audit(_mapper, _connection, _target): raise RuntimeError('审计写入失败')
    event.listen(WritingAdoption, 'before_insert', reject_audit)
    try:
        with job_db() as db:
            with pytest.raises(RuntimeError): accept(db, proposal_id)
    finally: event.remove(WritingAdoption, 'before_insert', reject_audit)
    with job_db() as db:
        assert db.get(WritingProposal, proposal_id).status == 'pending'
        assert db.get(Chapter, 1).content == '原文中的灯亮了。'
        assert db.query(ChapterRevision).count() == db.query(DerivedJob).count() == db.query(WritingAdoption).count() == 0

@pytest.mark.parametrize('change', ['version', 'content', 'lifecycle'])
def test_adoption_rejects_changed_source(job_db, change):
    proposal_id = proposal(job_db)
    with job_db() as db:
        chapter = db.get(Chapter, 1)
        if change == 'version': chapter.version += 1
        elif change == 'content': chapter.content = '其他编辑更新'
        else: chapter.rag_lifecycle_id = uuid4().hex
        db.commit()
        with pytest.raises(HTTPException) as exc: accept(db, proposal_id)
        assert exc.value.status_code == 409
        assert db.get(WritingProposal, proposal_id).status == 'pending'
        assert db.query(WritingAdoption).count() == 0

@pytest.mark.asyncio
async def test_deadline_call_limit_and_real_usage():
    fake = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
        SimpleNamespace(content='初稿', response_metadata={'token_usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}),
        SimpleNamespace(content='修正稿', usage_metadata={'input_tokens': 4, 'output_tokens': 5, 'total_tokens': 9})]))
    async with execution_scope(max_model_calls=2) as meter:
        await invoke_model(fake, '初稿'); await invoke_model(fake, '修稿')
        with pytest.raises(ExecutionBudgetError): await invoke_model(fake, '超限重试')
    assert meter.snapshot()['usage'] == {'input_tokens': 6, 'output_tokens': 8, 'total_tokens': 14}
    assert fake.ainvoke.await_count == 2
    assert all(type(call['latency_ms']) is int for call in meter.snapshot()['calls'])
    async def blocked(_): await asyncio.Event().wait()
    with pytest.raises(TimeoutError):
        async with execution_scope(timeout_seconds=.01) as deadline: await invoke_model(SimpleNamespace(ainvoke=blocked), '')
    assert deadline.snapshot()['error_code'] == 'deadline_exceeded'

@pytest.mark.asyncio
@pytest.mark.parametrize('mode,output', [
    ('outline', '{"chapters":[{"chapter_number":"1","title":"章","plot_points":["点"]}]}'),
    ('outline', '{"chapters":[{"chapter_number":2,"title":"章","plot_points":["点"]}]}'),
    ('character', '{"name":"假角色","personality":"勇敢"}')])
async def test_strict_task_output(mode, output):
    service = SimpleNamespace(prepare_messages=lambda **_: [('system', '共享上下文')],
        llm=SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=output))))
    with pytest.raises(ModelOutputError):
        await execute_task(mode=mode, service=service, context_pack=SimpleNamespace(), current_content='',
            instruction='结构候选', history=[], options=TaskOptions(target_chapters=1), novel_id=1,
            actor_id=1, novel_lifecycle_id='a'*32, target_chapter=1)


def test_jobs_api_persists_input_and_checks_identity(job_db, monkeypatch):
    """202立即持久输入，重复键冲突、跨账号与旧作品身份均受保护。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import generation
    from app.api.dependencies import get_current_user
    from app.db.base import get_db
    app = FastAPI(); app.include_router(generation.router, prefix='/generation')
    def database():
        with job_db() as db: yield db
    actor = SimpleNamespace(id=1)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: actor
    monkeypatch.setattr(generation, 'dispatch_job', lambda *_: None)
    with job_db() as db: lifecycle = db.get(Novel, 1).rag_lifecycle_id
    request_id = str(uuid4())
    payload = {'request_id': request_id, 'novel_id': 1, 'kind': 'chat', 'expected_novel_lifecycle_id': lifecycle,
        'payload': {'request_id': request_id, 'chapter_id': 1, 'message': '讨论', 'mode': 'discuss', 'current_content': '原文'}}
    with TestClient(app) as client:
        response = client.post('/generation/jobs', json=payload)
        assert response.status_code == 202, response.text
        job = response.json()
        assert (job['status'], job['chapter_id'], job['message'], job['chapter_title']) == ('queued', 1, '讨论', '第一章')
        assert client.post('/generation/jobs', json=payload).json()['id'] == job['id']
        payload['payload']['message'] = '不同指令'
        assert client.post('/generation/jobs', json=payload).status_code == 409
        actor.id = 2
        assert client.get(f"/generation/jobs/{job['id']}?novel_id=1").status_code == 404
        actor.id = 1
        assert client.post(f"/generation/jobs/{job['id']}/stop?novel_id=1").json()['status'] == 'cancelled'
        with job_db() as db:
            db.get(Novel, 1).rag_lifecycle_id = uuid4().hex; db.commit()
        assert client.get(f"/generation/jobs/{job['id']}?novel_id=1").status_code == 404


@pytest.mark.asyncio
async def test_sse_disconnect_keeps_persistent_generation(job_db, monkeypatch):
    """SSE只监听持久事件；连接断开后候选、最终事件与终态仍会完成。"""
    from app.api.routes import generation
    from app.models.schemas import GenerationResponse, FinalConsistencyStatus
    entered, release = Event(), Event()
    async def model_stream(*_args, **_kwargs):
        entered.set(); await asyncio.to_thread(release.wait)
        yield {'type': 'final_response', 'data': GenerationResponse(
            novel_id=1, chapter=1, final_content='灯下的人摘下斗笠。', agent_outputs=[], consistency_checks=[],
            retry_count=0, final_consistency=FinalConsistencyStatus(status='incomplete', has_conflict=False,
            retry_exhausted=False, is_complete=False, checks_skipped=['未执行'], violations=[]), generated_at=datetime.utcnow())}
    monkeypatch.setattr(generation.agent_service, 'generate_content_stream', model_stream)
    disconnected = SimpleNamespace(is_disconnected=AsyncMock(return_value=True))
    with job_db() as db:
        response = await generation.continue_chapter_stream(request=generation.ContinueRequest(
            novel_id=1, chapter_id=1, current_content='原文中的灯亮了。', use_rag_style=False),
            http_request=disconnected, current_user=SimpleNamespace(id=1), db=db)
        iterator = response.body_iterator
        assert 'job_id' in await anext(iterator)
        with pytest.raises(StopAsyncIteration): await anext(iterator)
    await asyncio.to_thread(entered.wait); release.set()
    await asyncio.wrap_future(list(writing_jobs._running.values())[0][1])
    with job_db() as db:
        job = db.query(WritingGenerationJob).one()
        assert job.status == 'completed'
        assert [item['type'] for item in job.result['events']] == ['metadata', 'chunk', 'done']
        assert db.query(WritingProposal).one().content == '灯下的人摘下斗笠。'


def test_duplicate_author_accepts_in_parallel_only_write_once(job_db):
    """两个独立连接并发确认相同请求，正文、原文版本和审计仅写一次。"""
    from concurrent.futures import ThreadPoolExecutor
    proposal_id = proposal(job_db); request_id = str(uuid4())
    def adopt():
        with job_db() as db:
            try:
                return accept(db, proposal_id, request_id)['chapter']
            except HTTPException as exc:
                assert exc.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: adopt(), range(2)))
    assert all(result is not None for result in results)
    assert results[0] == results[1]
    with job_db() as db:
        assert db.query(WritingAdoption).count() == db.query(ChapterRevision).count() == db.query(DerivedJob).count() == 1
        assert db.get(Chapter, 1).content.count('候选正文') == 1


@pytest.mark.asyncio
async def test_retry_prompt_contains_previous_candidate_and_specific_problems():
    """真实渲染的修稿请求同时包含旧候选及逐项问题，花括号不二次解释。"""
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from app.services.generation.workflow import AgentService
    seen = []
    async def answer(prompt):
        seen.extend(prompt.to_messages()); return AIMessage(content='修正候选')
    service = AgentService.__new__(AgentService); service.llm_complex = RunnableLambda(answer)
    previous = '他带着{神剑}瞬间横跨千里。'
    problem = '同一天从甲城到乙城违反{"距离":1000}的设定。'
    await service._agent_c_plot(dict(prompt='保持情节继续', worldview_output='世界', character_output='人物',
        story_bible_context=[], target_length=500, plot_output=previous,
        consistency_result={'has_conflict': True, 'violations': [problem]}, retry_count=1, workflow_steps=[]))
    assert previous in seen[0].content and problem in seen[0].content


def test_new_chapter_candidate_cannot_shift_to_later_chapter_on_accept(job_db):
    """新章候选冻结章号；作者已建下一章时不能静默改成再下一章。"""
    with job_db() as db:
        chapter = db.get(Chapter, 1)
        item = create_proposal(db, novel=db.get(Novel, 1), actor_id=1, chapter=chapter,
            base_content=chapter.content, operation='create', content='第二章候选', title='第二章',
            context_manifest={'scope': {'target_chapter': 2, 'memory_head_version': 0}})
        db.commit()
        db.add(Chapter(novel_id=1, chapter_number=2, title='作者自建第二章', content='作者正文')); db.commit()
        with pytest.raises(HTTPException) as exc: accept(db, item.id)
        assert exc.value.status_code == 409
        assert db.query(Chapter).count() == 2 and db.query(WritingAdoption).count() == 0
        assert db.get(WritingProposal, item.id).status == 'pending'


@pytest.mark.asyncio
async def test_sqlite_write_lock_does_not_block_http_event_loop(job_db, monkeypatch):
    """数据库写锁等待发生在线程内，HTTP事件循环仍按时响应其他协程。"""
    from threading import Thread, Timer
    from time import monotonic
    held, release = Event(), Event()
    def lock_database():
        with job_db.kw['bind'].connect() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            held.set(); release.wait(); connection.rollback()
    locker = Thread(target=lock_database); locker.start()
    await asyncio.to_thread(held.wait)
    model_threads = []
    async def model(_):
        model_threads.append(get_ident()); return SimpleNamespace(content='候选正文')
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    fallback = Timer(.4, release.set); fallback.start()
    try:
        with job_db() as request_db:
            main_thread = get_ident()
            data = writing_chat.TurnCreate(request_id=uuid4(), chapter_id=1, mode='continue', message='续写', current_content='原文中的灯亮了。')
            waiter = asyncio.create_task(writing_chat.send_turn(novel_id=1, data=data, db=request_db, user=SimpleNamespace(id=1)))
            started = monotonic()
            await asyncio.sleep(.03)
            assert monotonic() - started < .2
            release.set()
            result = await waiter
        assert result['status'] == 'completed'
        assert model_threads and model_threads[0] != main_thread
    finally:
        release.set(); fallback.cancel(); await asyncio.to_thread(locker.join)
