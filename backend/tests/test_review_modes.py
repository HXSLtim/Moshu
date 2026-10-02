"""审核模式:三档语义、守门与审计复用。"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from app.db.base import Base
from app.models.novel import Novel, Chapter
from app.models.user import User
from app.models.writing_chat import WritingProposal, WritingAdoption, WritingGenerationJob
from app.services.conversation import proposals


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([User(id=1, username='a', email='a@x.com', hashed_password='x')])
    session.commit()
    session.add_all([Novel(id=1, user_id=1, title='书', rag_lifecycle_id='l' * 32, review_mode='none')])
    session.commit()
    session.add_all([Chapter(id=1, novel_id=1, title='第1章', chapter_number=1, content='原文', rag_lifecycle_id='c' * 32, version=1)])
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _completed_job(db):
    db.add(WritingGenerationJob(id='job-1', request_id='req-1', novel_id=1, actor_id=1,
                                novel_lifecycle_id='l' * 32, kind='chat', payload={},
                                source_scope={}, status='completed',
                                started_at=datetime.utcnow(),
                                deadline_at=datetime.utcnow() + timedelta(hours=1),
                                finished_at=datetime.utcnow()))
    db.commit()


def _proposal(db, **overrides):
    row = WritingProposal(id='p1', novel_id=1, actor_id=1, novel_lifecycle_id='l' * 32,
                          chapter_id=1, chapter_lifecycle_id='c' * 32, base_version=1,
                          base_content_hash=proposals.content_hash('原文'), operation='append',
                          content='新段落', execution_job_id='job-1')
    for key, value in overrides.items():
        setattr(row, key, value)
    db.add(row)
    db.commit()
    return row


def test_confirm_mode_leaves_proposal_pending(db):
    db.query(Novel).update({'review_mode': 'confirm'})
    db.commit()
    _proposal(db)
    proposals.auto_apply_pending(db.get_bind(), 1, 1, 'job-1')
    assert db.query(WritingProposal).one().status == 'pending'


def test_none_mode_adopts_with_auto_audit(db):
    _completed_job(db)
    _proposal(db)
    proposals.auto_apply_pending(db.get_bind(), 1, 1, 'job-1')
    proposal = db.query(WritingProposal).one()
    assert proposal.status == 'accepted'
    audit = db.query(WritingAdoption).one()
    assert audit.request_id == 'auto:p1' and audit.decision == 'accept'
    chapter = db.get(Chapter, 1)
    assert '新段落' in chapter.content and chapter.version == 2


def test_auto_mode_gate_blocks_on_conflict(db):
    db.query(Novel).update({'review_mode': 'auto'})
    db.commit()
    _proposal(db)
    with patch.object(proposals, '_consistency_conflict', return_value=True):
        proposals.auto_apply_pending(db.get_bind(), 1, 1, 'job-1')
    assert db.query(WritingProposal).one().status == 'pending'


def test_auto_mode_adopts_when_consistency_passes(db):
    db.query(Novel).update({'review_mode': 'auto'})
    db.commit()
    _completed_job(db)
    _proposal(db)
    with patch.object(proposals, '_consistency_conflict', return_value=False):
        proposals.auto_apply_pending(db.get_bind(), 1, 1, 'job-1')
    assert db.query(WritingProposal).one().status == 'accepted'


def test_version_drift_falls_back_to_pending(db):
    _proposal(db)
    # 作者在候选生成后改了正文:基线漂移,CAS 必须拒绝自动采纳。
    db.query(Chapter).update({'content': '被作者改过的正文'})
    db.commit()
    proposals.auto_apply_pending(db.get_bind(), 1, 1, 'job-1')
    assert db.query(WritingProposal).one().status == 'pending'
