"""删除后仍须保留的投影 outbox，不依赖已删除作品的外键。"""
from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, JSON, String, UniqueConstraint
from app.db.base import Base
from app.models.memory import new_memory_id, utc_now


class ProjectionJob(Base):
    __tablename__ = 'projection_jobs'
    __table_args__ = (
        UniqueConstraint('kind', 'source_lifecycle_id', 'source_version', name='uq_projection_source'),
        CheckConstraint("state IN ('queued','running','succeeded','failed','superseded')", name='ck_projection_state'),
        Index('ix_projection_claim', 'state', 'available_at', 'lease_until'),
    )
    id = Column(String(36), primary_key=True, default=new_memory_id)
    novel_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    novel_lifecycle_id = Column(String(32), nullable=False)
    source_lifecycle_id = Column(String(32), nullable=False)
    source_version = Column(Integer, nullable=False)
    kind = Column(String(30), nullable=False)
    payload = Column(JSON, nullable=False)
    state = Column(String(20), nullable=False, default='queued')
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    available_at = Column(DateTime, nullable=False, default=utc_now)
    lease_token = Column(String(36))
    lease_until = Column(DateTime)
    error = Column(String(300))
    created_at = Column(DateTime, nullable=False, default=utc_now)
