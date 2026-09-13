"""小说级创作对话；候选文本与正式章节分开保存。"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.db.base import Base


class WritingTurn(Base):
    __tablename__ = "writing_turns"
    __table_args__ = (UniqueConstraint("novel_id", "request_id", name="uq_writing_turn_request"),)

    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    request_id = Column(String(36), nullable=False)
    chapter_id = Column(Integer, nullable=False)
    chapter_title = Column(String(200), nullable=False)
    mode = Column(String(20), nullable=False)
    user_text = Column(Text, nullable=False)
    assistant_text = Column(Text, nullable=False, default="")
    base_content_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    error = Column(String(300), nullable=True)
    context_manifest = Column(JSON, nullable=True)
    novel_lifecycle_id = Column(String(32), nullable=True)
    chapter_lifecycle_id = Column(String(32), nullable=True)
    base_version = Column(Integer, nullable=True)
    result = Column(JSON, nullable=True)
    proposal_id = Column(String(36), nullable=True)
    execution = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class WritingProposal(Base):
    """待确认正文与来源快照，模型执行从不直接修改作者章节。"""
    __tablename__ = 'writing_proposals'
    id = Column(String(36), primary_key=True)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    novel_lifecycle_id = Column(String(32), nullable=False)
    turn_id = Column(Integer, ForeignKey('writing_turns.id', ondelete='CASCADE'), nullable=True, unique=True)
    execution_job_id = Column(String(36), ForeignKey('writing_generation_jobs.id', ondelete='CASCADE'), nullable=True, index=True)
    chapter_id = Column(Integer, nullable=True)
    chapter_lifecycle_id = Column(String(32), nullable=True)
    base_version = Column(Integer, nullable=False)
    base_content_hash = Column(String(64), nullable=False)
    operation = Column(String(20), nullable=False)
    target_chapter_number = Column(Integer, nullable=True)
    selection_start = Column(Integer, nullable=True)
    selection_end = Column(Integer, nullable=True)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    context_manifest = Column(JSON, nullable=True)
    execution = Column(JSON, nullable=True)
    adopted_chapter_id = Column(Integer, nullable=True)
    adopted_version = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    decided_at = Column(DateTime, nullable=True)


class WritingAdoption(Base):
    """作者采纳/拒绝审计，与正文版本和派生任务共用提交边界。"""
    __tablename__ = 'writing_adoptions'
    __table_args__ = (UniqueConstraint('novel_lifecycle_id', 'request_id', name='uq_writing_adoption_request'),)
    id = Column(String(36), primary_key=True)
    proposal_id = Column(String(36), ForeignKey('writing_proposals.id', ondelete='CASCADE'), nullable=False, unique=True)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    actor_id = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    decision = Column(String(20), nullable=False)
    base_version = Column(Integer, nullable=False)
    base_content_hash = Column(String(64), nullable=False)
    candidate_content_hash = Column(String(64), nullable=False)
    approved_content_hash = Column(String(64), nullable=True)
    chapter_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class WritingGenerationJob(Base):
    """固定作者及来源的执行快照，完成结果可查询，过期执行显式失败。"""
    __tablename__ = 'writing_generation_jobs'
    __table_args__ = (UniqueConstraint('novel_lifecycle_id', 'request_id', name='uq_writing_job_request'),)
    id = Column(String(36), primary_key=True)
    request_id = Column(String(36), nullable=False)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    novel_lifecycle_id = Column(String(32), nullable=False)
    kind = Column(String(30), nullable=False)
    payload = Column(JSON, nullable=False)
    source_scope = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default='queued', index=True)
    result = Column(JSON, nullable=True)
    execution = Column(JSON, nullable=True)
    error = Column(String(300), nullable=True)
    error_code = Column(String(60), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    deadline_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
