"""原文版本、事务任务、只读来源与作者隔离闭环。"""
import hashlib
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import chapter_memory
from app.core.config import settings
from app.crud import novel as crud
from app.db.base import Base, get_db
from app.models.memory import ChapterDigest, ChapterRevision, DerivedJob
from app.models.novel import Chapter, Novel
from app.models.schemas import ChapterCreate, ChapterNextCreate, ChapterUpdate
from app.models.user import User
from app.services.memory.config import digest_recipe_version


@pytest.fixture
def memory_api(monkeypatch):
    """每例独立内存库，不启用真实模型或默认作者库。"""
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    db = sessions()
    author = User(id=1, username='记忆作者', email='memory@example.com', hashed_password='unused')
    other = User(id=2, username='其他作者', email='other-memory@example.com', hashed_password='unused')
    db.add_all([author, other]); db.commit()
    db.add_all([Novel(id=1, user_id=1, title='第一部'), Novel(id=2, user_id=2, title='别人的书')]); db.commit()
    first = crud.create_chapter(db, 1, ChapterCreate(chapter_number=1, title='初见', content='林夏获得青霜剑。'))
    second = crud.create_chapter(db, 2, ChapterCreate(chapter_number=1, title='隐秘', content='不得泄露的原文。'))
    app = FastAPI()
    app.include_router(chapter_memory.router, prefix='/api')
    app.dependency_overrides[get_current_user] = lambda: author
    def session_override():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = session_override
    monkeypatch.setattr(settings, 'MEMORY_WORKER_ENABLED', False)
    with TestClient(app) as client:
        yield client, db, first.id, second.id
    db.close(); engine.dispose()


def revision_for(db, chapter_id, version=1):
    return db.query(ChapterRevision).filter_by(chapter_id=chapter_id, version=version).one()


def completed_digest(db, chapter_id):
    revision = revision_for(db, chapter_id)
    result = ChapterDigest(novel_id=revision.novel_id, chapter_id=chapter_id,
        source_revision_id=revision.id, recipe_version=digest_recipe_version(),
        summary='林夏获得一把剑。', participants=['林夏'], events=['获得青霜剑'],
        state_change_candidates=['林夏可能持有青霜剑'], open_threads=[],
        source_refs=[{'revision_id': revision.id, 'start': 0, 'end': len(revision.content),
                     'quote': revision.content, 'content_hash': revision.content_hash}])
    db.add(result)
    db.query(DerivedJob).filter_by(source_revision_id=revision.id).update({'state': 'succeeded'})
    db.commit()
    return result


def test_saves_atomically_keep_revisions_and_supersede_old_tasks(memory_api):
    """创建和保存版本有对应任务；旧版本不可覆盖，运行中旧任务原子失效。"""
    client, db, chapter_id, _ = memory_api
    original = revision_for(db, chapter_id)
    job = db.query(DerivedJob).filter_by(source_revision_id=original.id).one()
    job.state, job.lease_token = 'running', str(uuid4()); db.commit()
    updated = crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, content='林夏把青霜剑交给同伴。'))
    assert updated.version == 2
    db.expire_all()
    assert job.state == 'superseded' and job.lease_token is None
    assert original.content == '林夏获得青霜剑。'
    latest = revision_for(db, chapter_id, 2)
    assert latest.content == updated.content
    assert latest.content_hash == hashlib.sha256(updated.content.encode()).hexdigest()
    assert db.query(DerivedJob).filter_by(source_revision_id=latest.id, state='queued').count() == 1
    page = client.get(f'/api/novels/1/chapters/{chapter_id}/revisions?limit=1').json()
    assert [item['version'] for item in page] == [2] and 'content' not in page[0]
    older = client.get(f'/api/novels/1/chapters/{chapter_id}/revisions?before_version=2').json()
    assert [item['version'] for item in older] == [1]
    source = client.get(f'/api/novels/1/revisions/{original.id}').json()
    assert source['content'] == original.content


@pytest.mark.parametrize('operation', ['create', 'create_next', 'update'])
def test_job_insert_failure_rolls_back_entire_chapter_operation(memory_api, operation):
    """任务存储失败不是保存成功，原文、版本和任务必须一起回滚。"""
    _, db, chapter_id, _ = memory_api
    before = (db.query(Chapter).count(), db.query(ChapterRevision).count(), db.query(DerivedJob).count())
    def reject_job(*_):
        raise RuntimeError('模拟任务磁盘写入失败')
    event.listen(DerivedJob, 'before_insert', reject_job)
    try:
        with pytest.raises(RuntimeError, match='模拟任务'):
            if operation == 'create':
                crud.create_chapter(db, 1, ChapterCreate(chapter_number=2, title='新章', content='新正文'))
            elif operation == 'create_next':
                crud.create_next_chapter(db, 1, ChapterNextCreate(content='新正文'))
            else:
                crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, content='未成功的新稿'))
    finally:
        event.remove(DerivedJob, 'before_insert', reject_job)
    db.expire_all()
    assert (db.query(Chapter).count(), db.query(ChapterRevision).count(), db.query(DerivedJob).count()) == before
    assert db.get(Chapter, chapter_id).version == 1
    assert db.get(Chapter, chapter_id).content == '林夏获得青霜剑。'
    assert db.query(DerivedJob).filter_by(source_revision_id=revision_for(db, chapter_id).id).one().state == 'queued'


def test_conflicting_save_cannot_create_memory_or_invalidate_latest(memory_api):
    """409 冲突不产生历史，也不能将已成功简介误标过期。"""
    _, db, chapter_id, _ = memory_api
    digest = completed_digest(db, chapter_id)
    with pytest.raises(crud.ChapterVersionConflictError):
        crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=99, content='冲突稿'))
    db.expire_all()
    assert digest.status == 'ready'
    assert db.query(ChapterRevision).filter_by(chapter_id=chapter_id).count() == 1


def test_digest_becomes_stale_on_edit_but_source_remains_readable(memory_api):
    """旧简介仅供只读回查，改稿后不得继续显示为当前版本记忆。"""
    client, db, chapter_id, _ = memory_api
    digest = completed_digest(db, chapter_id)
    endpoint = f'/api/novels/1/chapters/{chapter_id}/digest'
    assert client.get(endpoint).json()['status'] == 'ready'
    crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, title='改过的章名'))
    result = client.get(endpoint).json()
    assert result['status'] == 'stale' and result['current_version'] == 2
    assert result['digest']['source_version'] == 1 and result['job']['state'] == 'queued'
    assert result['worker_enabled'] is False
    assert client.get(f'/api/novels/1/revisions/{digest.source_revision_id}').status_code == 200


def test_rebuild_reuses_task_and_explicitly_retries_failure(memory_api):
    """重复重建复用同任务，手动重试开启新一轮有界尝试但不重复排队。"""
    client, db, chapter_id, _ = memory_api
    endpoint = f'/api/novels/1/chapters/{chapter_id}/digest/rebuild'
    first = client.post(endpoint)
    assert first.status_code == 202
    job_id = first.json()['id']
    assert client.post(endpoint).json()['id'] == job_id
    job = db.get(DerivedJob, job_id)
    job.state, job.attempts, job.error_message = 'failed', 3, '错误'; db.commit()
    result = client.post(endpoint).json()
    assert result['id'] == job_id and result['state'] == 'queued' and result['attempts'] == 0
    assert result['error_message'] is None
    assert db.query(DerivedJob).filter_by(source_revision_id=revision_for(db, chapter_id).id).count() == 1
    assert client.get(f'/api/memory-jobs/{job_id}').json()['state'] == 'queued'


def test_memory_endpoints_enforce_author_and_parent_scope(memory_api):
    """新接口均不能跨作者读原文/简介/任务或触发重建。"""
    client, db, chapter_id, other_chapter = memory_api
    revision = revision_for(db, other_chapter)
    job = db.query(DerivedJob).filter_by(source_revision_id=revision.id).one()
    for path in [f'/api/novels/2/chapters/{other_chapter}/digest',
                 f'/api/novels/1/chapters/{other_chapter}/revisions',
                 f'/api/novels/2/revisions/{revision.id}', f'/api/novels/1/revisions/{revision.id}',
                 f'/api/memory-jobs/{job.id}']:
        assert client.get(path).status_code == 404
    assert client.post(f'/api/novels/2/chapters/{other_chapter}/digest/rebuild').status_code == 404
    assert client.post(f'/api/novels/1/chapters/{other_chapter}/digest/rebuild').status_code == 404


def test_deleted_chapter_id_reuse_cannot_inherit_revisions_or_jobs(memory_api):
    """聚合删除清理历史与简介，重建相同整数 ID 不继承旧生命周期。"""
    client, db, chapter_id, _ = memory_api
    digest = completed_digest(db, chapter_id)
    revision_id = digest.source_revision_id
    job_id = db.query(DerivedJob).filter_by(source_revision_id=revision_id).one().id
    assert crud.delete_chapter(db, chapter_id)
    db.add(Chapter(id=chapter_id, novel_id=1, chapter_number=1, title='新生命周期', content='新的原文'))
    db.commit()
    assert client.get(f'/api/novels/1/revisions/{revision_id}').status_code == 404
    assert client.get(f'/api/memory-jobs/{job_id}').status_code == 404
    assert client.get(f'/api/novels/1/chapters/{chapter_id}/digest').json()['digest'] is None


@pytest.mark.parametrize('content', ['', '字' * 500001], ids=['空白', '旧库超长章'])
def test_explicit_rebuild_rejects_empty_or_over_budget_source(memory_api, content):
    """不把空白或截断正文当作整章提取输入，失败不会创建新的重建任务。"""
    client, db, chapter_id, _ = memory_api
    if len(content) > 500000:
        # 模拟旧库已有的超长正文；新版写入Schema本身已禁止该输入。
        db.query(Chapter).filter_by(id=chapter_id).update({'content': content, 'version': 2})
        db.commit()
    else:
        crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, content=content))
    before = db.query(DerivedJob).count()
    response = client.post(f'/api/novels/1/chapters/{chapter_id}/digest/rebuild')
    assert response.status_code == 422
    assert db.query(DerivedJob).count() == before


async def test_save_extract_edit_rebuild_and_read_source_end_to_end(memory_api):
    """真实保存事务与worker发布连接到API，改稿后只发布最新来源简介。"""
    from app.services.memory.worker import MemoryWorker
    client, db, chapter_id, _ = memory_api
    class Extractor:
        async def extract(self, revision):
            return {'summary': revision.content, 'participants': [], 'events': [],
                    'state_change_candidates': [], 'open_threads': [],
                    'source_refs': [{'start': 0, 'quote': revision.content}]}
    worker = MemoryWorker(session_factory=sessionmaker(bind=db.get_bind()), extractor=Extractor())
    endpoint = f'/api/novels/1/chapters/{chapter_id}/digest'
    first_source = revision_for(db, chapter_id).id
    while await worker.run_once():
        pass
    ready = client.get(endpoint).json()
    assert ready['status'] == 'ready'
    assert ready['digest']['source_refs'][0]['revision_id'] == first_source
    assert ready['job']['state'] == 'succeeded'
    crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, content='剑留在林夏手中。'))
    assert client.get(endpoint).json()['status'] == 'stale'
    assert await worker.run_once()
    latest = client.get(endpoint).json()
    assert latest['status'] == 'ready' and latest['digest']['source_version'] == 2
    assert latest['digest']['summary'] == '剑留在林夏手中。'
    assert client.get(f'/api/novels/1/revisions/{first_source}').json()['content'] == '林夏获得青霜剑。'


def test_restore_creates_new_revision_and_cancel_is_terminal(memory_api):
    """作者恢复产生新版本和新任务，旧来源保留，取消不能影响其他任务。"""
    client, db, chapter_id, _ = memory_api
    source = revision_for(db, chapter_id)
    source_id = source.id
    original = source.content
    chapter = crud.update_chapter(db, chapter_id, ChapterUpdate(expected_version=1, content='后来修改。'))
    response = client.post(f'/api/novels/1/revisions/{source_id}/restore', json={
        'expected_version': 2, 'expected_chapter_lifecycle_id': chapter.rag_lifecycle_id, 'expected_novel_lifecycle_id': db.get(Novel, 1).rag_lifecycle_id})
    assert response.status_code == 200
    assert response.json()['version'] == 3 and response.json()['content'] == original
    db.expire_all()
    assert revision_for(db, chapter_id, 2).content == '后来修改。'
    assert revision_for(db, chapter_id).content == original
    assert client.post(f'/api/novels/1/revisions/{source_id}/restore', json={
        'expected_version': 2, 'expected_chapter_lifecycle_id': chapter.rag_lifecycle_id, 'expected_novel_lifecycle_id': db.get(Novel, 1).rag_lifecycle_id}).status_code == 409
    job = db.query(DerivedJob).filter_by(source_revision_id=revision_for(db, chapter_id, 3).id).one()
    cancelled = client.post(f'/api/memory-jobs/{job.id}/cancel')
    assert cancelled.status_code == 200 and cancelled.json()['state'] == 'cancelled'
    assert client.post(f'/api/memory-jobs/{job.id}/cancel').json()['state'] == 'cancelled'
