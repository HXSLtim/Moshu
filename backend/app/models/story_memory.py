"""结构化剧情与状态审阅；正式状态仍只存 StoryFact。"""
from uuid import uuid4
from sqlalchemy import CheckConstraint, Column, Integer, String, Text, JSON, ForeignKey, UniqueConstraint
from app.db.base import Base


def memory_uuid():
    return str(uuid4())


class StoryMemoryHead(Base):
    __tablename__ = "story_memory_heads"
    __table_args__ = (CheckConstraint("version >= 0", name="ck_story_memory_version"),)
    novel_id = Column(Integer, ForeignKey("novels.id"), primary_key=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False, default=0)


class StoryEntity(Base):
    __tablename__ = "story_entities"
    __table_args__ = (
        CheckConstraint("kind IN ('character','item','location','organization')", name="ck_story_entity_kind"),
        CheckConstraint("length(trim(name)) > 0", name="ck_story_entity_name"),
    )
    id = Column(String(36), primary_key=True, default=memory_uuid)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False, default="", server_default="")
    kind = Column(String(20), nullable=False)


class OutlineNode(Base):
    __tablename__ = "story_outline_nodes"
    __table_args__ = (
        CheckConstraint("kind IN ('volume','chapter','scene')", name="ck_story_outline_kind"),
        CheckConstraint("plot_status IN ('planned','occurred')", name="ck_story_outline_plot_status"),
        CheckConstraint("origin IN ('author','ai')", name="ck_story_outline_origin"),
        CheckConstraint("source_status IN ('ready','needs_review')", name="ck_story_outline_source_status"),
        CheckConstraint("chapter_number IS NULL OR chapter_number > 0", name="ck_story_outline_chapter"),
        CheckConstraint("kind = 'volume' OR chapter_number IS NOT NULL", name="ck_story_outline_position"),
        CheckConstraint("length(trim(title)) > 0", name="ck_story_outline_title"),
    )
    id = Column(String(36), primary_key=True, default=memory_uuid)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    parent_id = Column(String(36), nullable=True)
    kind = Column(String(20), nullable=False)
    plot_status = Column(String(20), nullable=False)
    chapter_number = Column(Integer)
    title = Column(String(200), nullable=False)
    conflict = Column(Text, nullable=False, default="")
    outcome = Column(Text, nullable=False, default="")
    origin = Column(String(20), nullable=False, default="author")
    source_refs = Column(JSON, nullable=False, default=list)
    source_status = Column(String(20), nullable=False, default="ready")


class StateCandidate(Base):
    __tablename__ = "story_state_candidates"
    __table_args__ = (
        CheckConstraint("effective_chapter > 0", name="ck_story_candidate_chapter"),
        CheckConstraint("status IN ('pending','confirmed','rejected','revoked')", name="ck_story_candidate_status"),
        CheckConstraint("source_status IN ('ready','needs_review')", name="ck_story_candidate_source_status"),
        CheckConstraint("length(trim(attribute)) > 0 AND length(trim(value)) > 0", name="ck_story_candidate_value"),
        CheckConstraint("status NOT IN ('confirmed','revoked') OR fact_id IS NOT NULL", name="ck_story_candidate_fact"),
    )
    id = Column(String(36), primary_key=True, default=memory_uuid)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    entity_id = Column(String(36), nullable=False)
    attribute = Column(String(100), nullable=False)
    value = Column(Text, nullable=False)
    value_entity_id = Column(String(36))
    effective_chapter = Column(Integer, nullable=False)
    source_refs = Column(JSON, nullable=False, default=list)
    source_status = Column(String(20), nullable=False, default="ready")
    status = Column(String(20), nullable=False, default="pending")
    reason = Column(Text, nullable=False, default="")
    fact_id = Column(Integer, nullable=True)


class StoryMemoryCommand(Base):
    __tablename__ = "story_memory_commands"
    __table_args__ = (UniqueConstraint("novel_lifecycle_id", "request_id", name="uq_story_memory_request"),)
    id = Column(String(36), primary_key=True, default=memory_uuid)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    novel_lifecycle_id = Column(String(32), nullable=False)
    request_id = Column(String(36), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    result = Column(JSON, nullable=False)
