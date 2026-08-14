"""结构化 Story Bible:事实账本与剧情事件模型。

设计边界(与 `ARCHITECTURE.md` 领域边界一致):
- 事实(`StoryFact`)是作者确认过的、可被一致性检查校验的陈述,
  按「主体 + 属性 + 值」建模,状态流转 active → retired 保留历史,
  不物理删除旧值,保证"事实账本"可追溯。
- 事件(`StoryEvent`)是发生在故事时间轴上的关键节点,
  携带伏笔描述,为后续"伏笔回收清单"提供落点。
- 两张表都不直接暴露 AI 分析产物;AI 只能生成候选,由作者确认后写入。
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.db.base import Base


class StoryFact(Base):
    """作者确认的故事内事实(角色位置、身份、持有物等)。"""

    __tablename__ = "story_facts"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)

    # 事实三元组:主体(角色/地点/组织名)+ 属性 + 值。
    subject = Column(String(100), nullable=False)
    attribute = Column(String(100), nullable=False)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    # 事实生命周期:在哪章确立、在哪章失效。
    chapter_established = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    retired_chapter = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<StoryFact {self.subject}.{self.attribute}={self.value!r}>"


class StoryEvent(Base):
    """剧情事件:故事时间轴上的关键节点。"""

    __tablename__ = "story_events"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False, index=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)

    # 故事内时间定位。
    story_day = Column(Integer, nullable=False, default=1)
    chapter = Column(Integer, nullable=True)

    # 关联角色名列表(允许先记名、后建角色卡)。
    involved_characters = Column(JSON, default=list)
    # 该事件埋下的伏笔/线索,后续与伏笔回收清单对齐。
    foreshadowing = Column(Text, nullable=True)

    # planned=大纲阶段规划,occurred=正文中已发生。
    status = Column(String(20), nullable=False, default="planned", index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<StoryEvent day={self.story_day} {self.title!r}>"
