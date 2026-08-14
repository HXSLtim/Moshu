"""
小说数据模型
"""
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


def _new_rag_lifecycle_id() -> str:
    """生成不可由数据库主键复用冒充的RAG生命周期标识。"""
    return uuid4().hex


class Novel(Base):
    """小说模型"""
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    genre = Column(String(50), nullable=True)  # 题材类型：玄幻、都市、科幻等
    worldview = Column(Text, nullable=True)  # 世界观设定
    rag_lifecycle_id = Column(
        String(32),
        nullable=False,
        unique=True,
        default=_new_rag_lifecycle_id,
    )
    rag_revision = Column(Integer, nullable=False, default=1, server_default="1")

    # 外键关联用户
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关联关系
    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
    style_samples = relationship("StyleSample", back_populates="novel", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="novel", cascade="all, delete-orphan")
    worldview_settings = relationship("WorldviewSetting", back_populates="novel", cascade="all, delete-orphan")
    plot_elements = relationship("PlotElement", back_populates="novel", cascade="all, delete-orphan")
    story_timelines = relationship("StoryTimeline", back_populates="novel", cascade="all, delete-orphan")
    novel_outlines = relationship("NovelOutline", back_populates="novel", cascade="all, delete-orphan")
    style_guides = relationship("StyleGuide", back_populates="novel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Novel {self.title}>"


class Chapter(Base):
    """章节模型"""
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uq_chapters_novel_number"),
        CheckConstraint("chapter_number > 0", name="ck_chapters_number_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False)  # 章节号
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    word_count = Column(Integer, default=0)  # 字数统计
    version = Column(Integer, nullable=False, default=1, server_default="1")
    rag_lifecycle_id = Column(
        String(32),
        nullable=False,
        unique=True,
        default=_new_rag_lifecycle_id,
    )

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关联关系
    novel = relationship("Novel", back_populates="chapters")


class StyleSample(Base):
    __tablename__ = "style_samples"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    sample_text = Column(Text, nullable=False)
    style_features = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    novel = relationship("Novel", back_populates="style_samples")

    def __repr__(self):
        return f"<StyleSample {self.name}>"
