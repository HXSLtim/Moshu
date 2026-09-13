"""投影任务验证真实事务、崩溃租约与旧生命周期重放。"""
from datetime import timedelta
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.models
from app.db.base import Base
from app.models.user import User
from app.models.novel import Novel, Chapter
from app.models.memory import ChapterRevision, utc_now
from app.models.projection_job import ProjectionJob
from app.models.schemas import ChapterCreate, ChapterUpdate, ChapterNextCreate
from app.crud import novel as crud
from app.services.projection_jobs import ProjectionWorker


@pytest.fixture
def projection_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = User(username='投影作者', email='projection@example.com', hashed_password='unused')
        db.add(user); db.flush()
        novel = Novel(title='投影测试', user_id=user.id)
        db.add(novel); db.commit()
        yield db, sessions, novel
    engine.dispose()


def make_chapter(db, novel):
    return crud.create_chapter(db, novel.id, ChapterCreate(chapter_number=1, title='初稿', content='旧稿'))


def test_source_change_and_outbox_rollback(projection_db):
    """任务失败时正文与新章都回滚，更新会撤销旧任务。"""
    db, _, novel = projection_db
    chapter = make_chapter(db, novel)
    old = db.query(ProjectionJob).one()
    crud.update_chapter(db, chapter.id, ChapterUpdate(expected_version=1, content='新稿'))
    db.expire_all()
    assert old.state == 'superseded'
    def fail(*_):
        raise RuntimeError('模拟outbox写入失败')
    event.listen(ProjectionJob, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError):
            crud.update_chapter(db, chapter.id, ChapterUpdate(expected_version=2, content='不能保存'))
        with pytest.raises(RuntimeError):
            crud.create_next_chapter(db, novel.id, ChapterNextCreate(content='不能创建'))
    finally:
        event.remove(ProjectionJob, 'before_insert', fail)
    assert db.get(Chapter, chapter.id).content == '新稿'
    assert db.query(Chapter).count() == 1
    assert db.query(ChapterRevision).count() == 2


def test_composable_save_and_scope_conflict(projection_db):
    """可组合保存不擅自提交，错误来源即使版本相同也拒绝。"""
    db, _, novel = projection_db
    chapter = make_chapter(db, novel)
    with pytest.raises(crud.ChapterVersionConflictError):
        crud.update_chapter(db, chapter.id, ChapterUpdate(expected_version=1, content='错误身份', expected_chapter_lifecycle_id='0'*32))
    crud.update_chapter(db, chapter.id, ChapterUpdate(expected_version=1, content='未提交'), commit=False)
    db.rollback()
    assert db.get(Chapter, chapter.id).content == '旧稿'
    crud.create_next_chapter(db, novel.id, ChapterNextCreate(content='未提交新章'), commit=False)
    db.rollback()
    assert db.query(Chapter).count() == 1


def test_restart_reclaims_lease_and_rejects_old_publisher(projection_db):
    """新worker重领过期租约，旧worker无法发布。"""
    db, sessions, novel = projection_db
    make_chapter(db, novel)
    worker = ProjectionWorker(sessions, AsyncMock())
    old = worker.claim()
    assert old and worker.claim() is None
    db.query(ProjectionJob).update({'lease_until': utc_now()-timedelta(seconds=1)}); db.commit()
    new = worker.claim()
    assert new['lease_token'] != old['lease_token']
    assert not worker.finish(old, 'succeeded')
    assert worker.finish(new, 'succeeded')


def test_expired_lease_cannot_publish_without_new_claim(projection_db):
    """没有其他worker接手时，租约过期也必须拒绝迟到终态。"""
    db, sessions, novel = projection_db
    make_chapter(db, novel)
    worker = ProjectionWorker(sessions, AsyncMock())
    job = worker.claim()
    db.query(ProjectionJob).update({'lease_until': utc_now()-timedelta(seconds=1)})
    db.commit()
    assert not worker.finish(job, 'succeeded')
    db.expire_all()
    assert db.query(ProjectionJob).one().state == 'running'
    db.query(ProjectionJob).update({'lease_until': None})
    db.commit()
    recovered = worker.claim()
    assert recovered and recovered['lease_token'] != job['lease_token']


@pytest.mark.asyncio
async def test_delete_cleanup_survives_id_reuse(projection_db):
    """清理只针对已删除来源，新章即使复用整数ID仍可索引。"""
    db, sessions, novel = projection_db
    chapter = make_chapter(db, novel)
    original_lifecycle = chapter.rag_lifecycle_id
    crud.delete_chapter(db, chapter.id)
    replacement = make_chapter(db, novel)
    assert replacement.rag_lifecycle_id != original_lifecycle
    service = AsyncMock()
    service.index_content.return_value = True
    worker = ProjectionWorker(sessions, service)
    while await worker.run_once():
        pass
    service.cleanup_projection_strict.assert_awaited_once()
    assert service.cleanup_projection_strict.call_args.args[1]['_source_lifecycle'] == original_lifecycle
    service.index_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_failures_are_finite(projection_db):
    """服务失败不能记录成功，有限重试结束后需显式重建。"""
    db, sessions, novel = projection_db
    make_chapter(db, novel)
    service = AsyncMock()
    service.index_content.return_value = False
    worker = ProjectionWorker(sessions, service)
    for _ in range(3):
        assert await worker.run_once()
        db.query(ProjectionJob).update({'available_at': utc_now()-timedelta(seconds=1)}); db.commit()
    db.expire_all()
    assert db.query(ProjectionJob).one().state == 'failed'
    assert not await worker.run_once()
    assert service.index_content.await_count == 3
