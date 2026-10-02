"""持久任务在竞争、改稿、取消、租约恢复和模型失败时的发布边界。"""
import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.memory import ChapterDigest, ChapterRevision, DerivedJob, utc_now
from app.models.novel import Chapter, Novel
from app.models.user import User
from app.services.memory.digest import DigestExtractionError
from app.services.memory.config import digest_recipe_version
from app.services.memory.worker import MemoryWorker


def result():
    return {"summary": "李明交剑。", "participants": ["李明"], "events": ["交剑"],
            "state_change_candidates": ["剑已转交"], "open_threads": [],
            "source_refs": [{"quote": "李明", "start": 0}]}


@pytest.fixture
def memory_db(tmp_path):
    """使用文件数据库验证独立连接，而非共享单连接掩盖事务边界。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(id=1, username="作者", email="author@example.com", hashed_password="unused"))
        db.add(Novel(id=1, user_id=1, title="小说", rag_lifecycle_id="novel-life"))
        db.add(Chapter(id=1, novel_id=1, chapter_number=1, title="交剑", content="李明交剑。", version=1,
                       rag_lifecycle_id="chapter-life"))
        db.flush()
        db.add(ChapterRevision(id="revision-1", novel_id=1, chapter_id=1, novel_lifecycle_id="novel-life",
            chapter_lifecycle_id="chapter-life", version=1, chapter_number=1, title="交剑", content="李明交剑。",
            content_hash=hashlib.sha256("李明交剑。".encode()).hexdigest()))
        db.flush()
        db.add(DerivedJob(id="job-1", novel_id=1, novel_lifecycle_id="novel-life", source_revision_id="revision-1",
                          recipe_version=digest_recipe_version()))
        db.commit()
    yield sessions
    engine.dispose()


def inspect_job(sessions):
    with sessions() as db:
        job = db.get(DerivedJob, "job-1")
        return job.state, job.attempts, job.error_code, job.error_message, db.query(ChapterDigest).count()


@pytest.mark.asyncio
async def test_two_workers_publish_once_without_holding_transaction(memory_db):
    entered, release = asyncio.Event(), asyncio.Event()
    async def extract(_revision):
        entered.set()
        await release.wait()
        return result()
    extractor = SimpleNamespace(extract=AsyncMock(side_effect=extract))
    first = asyncio.create_task(MemoryWorker(memory_db, extractor).run_once())
    await entered.wait()
    # 另一个连接可以写入，且不可领取尚在租约内的任务。
    with memory_db() as db:
        db.execute(update(Novel).values(description="模型执行期间可写"))
        db.commit()
    assert not await MemoryWorker(memory_db, extractor).run_once()
    release.set()
    await first
    assert inspect_job(memory_db) == ("succeeded", 1, None, None, 1)
    assert extractor.extract.await_count == 1
    assert not await MemoryWorker(memory_db, extractor).run_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "lifecycle", "content", "title", "novel_lifecycle", "cancel", "delete"])
async def test_late_result_cannot_publish_after_source_or_state_change(memory_db, change):
    async def extract(_revision):
        with memory_db() as db:
            if change == "version":
                db.execute(update(Chapter).values(version=2))
            elif change == "lifecycle":
                db.execute(update(Chapter).values(rag_lifecycle_id="new-chapter"))
            elif change == "content":
                db.execute(update(Chapter).values(content="正文改变"))
            elif change == "title":
                db.execute(update(Chapter).values(title="新标题"))
            elif change == "novel_lifecycle":
                db.execute(update(Novel).values(rag_lifecycle_id="new-novel"))
            elif change == "cancel":
                db.execute(update(DerivedJob).values(state="cancelled"))
            else:
                db.delete(db.get(Chapter, 1))
            db.commit()
        return result()
    await MemoryWorker(memory_db, SimpleNamespace(extract=extract)).run_once()
    with memory_db() as db:
        assert db.query(ChapterDigest).count() == 0
        job = db.get(DerivedJob, "job-1")
        assert job is None if change == "delete" else job.state == ("cancelled" if change == "cancel" else "superseded")


@pytest.mark.asyncio
async def test_expired_lease_recovers_after_restart_and_old_token_cannot_publish(memory_db):
    old = MemoryWorker(memory_db, SimpleNamespace(extract=AsyncMock(return_value=result())))
    claim, _ = old._claim()
    old_job, _ = claim
    with memory_db() as db:
        db.execute(update(DerivedJob).values(lease_until=utc_now() - timedelta(seconds=1)))
        db.commit()
    restarted = MemoryWorker(memory_db, SimpleNamespace(extract=AsyncMock(return_value=result())))
    assert await restarted.run_once()
    old._publish(old_job, result())
    assert inspect_job(memory_db) == ("succeeded", 2, None, None, 1)


@pytest.mark.asyncio
async def test_expired_exhausted_lease_becomes_failed_without_model(memory_db):
    with memory_db() as db:
        db.execute(update(DerivedJob).values(state="running", attempts=3,
            lease_token="abandoned", lease_until=utc_now() - timedelta(seconds=1)))
        db.commit()
    extractor = SimpleNamespace(extract=AsyncMock())
    assert await MemoryWorker(memory_db, extractor).run_once()
    assert inspect_job(memory_db)[:3] == ("failed", 3, "attempts_exhausted")
    extractor.extract.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [(TimeoutError(), "timeout"), (RuntimeError("secret-key-provider-body"), "extraction_failed")])
async def test_retry_is_bounded_and_errors_are_sanitized(memory_db, error, code):
    extractor = SimpleNamespace(extract=AsyncMock(side_effect=error))
    worker = MemoryWorker(memory_db, extractor)
    for attempt in range(1, 4):
        assert await worker.run_once()
        state, attempts, actual_code, message, count = inspect_job(memory_db)
        assert state == ("queued" if attempt < 3 else "failed")
        assert attempts == attempt and actual_code == code and count == 0
        assert "secret-key" not in message
        if attempt < 3:
            assert not await worker.run_once()
            with memory_db() as db:
                db.execute(update(DerivedJob).values(available_at=utc_now() - timedelta(seconds=1)))
                db.commit()
    assert extractor.extract.await_count == 3


@pytest.mark.asyncio
async def test_budget_failure_is_terminal(memory_db):
    extractor = SimpleNamespace(extract=AsyncMock(side_effect=DigestExtractionError("source_budget", "原文超限")))
    await MemoryWorker(memory_db, extractor).run_once()
    assert inspect_job(memory_db)[:3] == ("failed", 1, "source_budget")


@pytest.mark.asyncio
async def test_old_recipe_is_superseded_before_model(memory_db):
    with memory_db() as db:
        db.execute(update(DerivedJob).values(recipe_version="old-recipe"))
        db.commit()
    extractor = SimpleNamespace(extract=AsyncMock())
    await MemoryWorker(memory_db, extractor).run_once()
    assert inspect_job(memory_db)[0] == "superseded"
    extractor.extract.assert_not_called()


@pytest.mark.asyncio
async def test_process_cancellation_preserves_lease_for_recovery(memory_db):
    entered = asyncio.Event()
    async def blocked(_revision):
        entered.set()
        await asyncio.Event().wait()
    task = asyncio.create_task(MemoryWorker(memory_db, SimpleNamespace(extract=blocked)).run_once())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inspect_job(memory_db)[:2] == ("running", 1)


@pytest.mark.asyncio
async def test_invalid_reference_from_injected_extractor_never_publishes(memory_db):
    invalid = result()
    invalid["source_refs"][0]["start"] = 99
    await MemoryWorker(memory_db, SimpleNamespace(extract=AsyncMock(return_value=invalid))).run_once()
    state, _, code, _, count = inspect_job(memory_db)
    assert state == "queued" and code == "invalid_reference" and count == 0


def test_simultaneous_claims_have_single_lease(memory_db):
    """两个真实线程同时领取时，数据库条件写入只授予一个租约。"""
    barrier = Barrier(2)
    def claim():
        barrier.wait()
        return MemoryWorker(memory_db)._claim()[0]
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim(), range(2)))
    assert sum(item is not None for item in claims) == 1
    assert inspect_job(memory_db)[:2] == ("running", 1)


def test_stolen_or_expired_lease_cannot_publish_or_fail_new_owner(memory_db):
    worker = MemoryWorker(memory_db)
    claim, _ = worker._claim()
    old_job, _ = claim
    with memory_db() as db:
        db.execute(update(DerivedJob).values(lease_token="new-owner"))
        db.commit()
    worker._publish(old_job, result())
    worker._fail(old_job, RuntimeError("迟到失败"))
    assert inspect_job(memory_db) == ("running", 1, None, None, 0)
    with memory_db() as db:
        db.execute(update(DerivedJob).values(lease_token=old_job.lease_token,
            lease_until=utc_now() - timedelta(seconds=1)))
        db.commit()
    worker._publish(old_job, result())
    assert inspect_job(memory_db) == ("running", 1, None, None, 0)


@pytest.mark.asyncio
async def test_worker_deadline_bounds_a_hanging_extractor(memory_db, monkeypatch):
    """即使适配器忘记实现超时，执行器也会结束本次尝试。"""
    from app.services.memory.worker import settings
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 0.01)
    async def blocked(_revision):
        await asyncio.Event().wait()
    await MemoryWorker(memory_db, SimpleNamespace(extract=blocked)).run_once()
    assert inspect_job(memory_db)[:3] == ("queued", 1, "timeout")


@pytest.mark.asyncio
async def test_stopped_worker_does_not_start_new_task(memory_db):
    stop = asyncio.Event()
    stop.set()
    extractor = SimpleNamespace(extract=AsyncMock())
    await MemoryWorker(memory_db, extractor).run_forever(stop)
    extractor.extract.assert_not_called()
    assert inspect_job(memory_db)[:2] == ("queued", 0)


@pytest.mark.asyncio
async def test_obsolete_job_backlog_yields_to_other_requests(memory_db):
    """清理无需模型等待的旧任务时，并行请求能运行且可及时停止循环。"""
    stop = asyncio.Event()
    processed = 0
    class BackloggedWorker(MemoryWorker):
        async def run_once(self):
            nonlocal processed
            processed += 1
            # 上限仅用于避免回归时测试本身成为永久阻塞。
            if processed == 100:
                stop.set()
            return True
    async def request_shutdown():
        stop.set()
    running = asyncio.create_task(BackloggedWorker(memory_db).run_forever(stop))
    other_request = asyncio.create_task(request_shutdown())
    await asyncio.gather(running, other_request)
    assert processed == 1
