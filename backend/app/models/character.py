"""
角色模型定义
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base


class Character(Base):
    """角色模型"""
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False)
    name = Column(String(100), nullable=False, index=True)
    
    # 基本信息
    age = Column(Integer)
    gender = Column(String(20))
    occupation = Column(String(100))
    
    # 外貌描述
    appearance = Column(Text)
    
    # 性格特征
    personality = Column(Text)
    
    # 背景故事
    background = Column(Text)
    
    # 技能和能力
    skills = Column(JSON, default=list)  # 存储技能列表
    
    # 关系网络
    relationships = Column(JSON, default=dict)  # 存储与其他角色的关系
    
    # 角色弧线
    character_arc = Column(Text)  # 角色发展轨迹
    
    # 重要性级别 (main, secondary, minor)
    importance_level = Column(String(20), default="secondary")
    
    # 首次出现章节
    first_appearance_chapter = Column(Integer)
    
    # 最后出现章节
    last_appearance_chapter = Column(Integer)
    
    # AI分析结果
    ai_analysis = Column(JSON, default=dict)  # AI对角色的分析
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    novel = relationship("Novel", back_populates="characters")
    appearances = relationship("CharacterAppearance", back_populates="character", cascade="all, delete-orphan")
    relationships_as_a = relationship(
        "CharacterRelationship", foreign_keys="CharacterRelationship.character_a_id",
        back_populates="character_a", cascade="all, delete-orphan",
    )
    relationships_as_b = relationship(
        "CharacterRelationship", foreign_keys="CharacterRelationship.character_b_id",
        back_populates="character_b", cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Character {self.name}>"


class CharacterRelationship(Base):
    """角色关系模型"""
    __tablename__ = "character_relationships"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id"), nullable=False)
    
    # 关系双方
    character_a_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    character_b_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    
    # 关系类型 (friend, enemy, family, romantic, mentor, etc.)
    relationship_type = Column(String(50), nullable=False)
    
    # 关系描述
    description = Column(Text)
    
    # 关系强度 (1-10)
    strength = Column(Integer, default=5)
    
    # 关系发展阶段
    development_stage = Column(String(50))  # initial, developing, established, declining
    
    # 首次建立关系的章节
    established_in_chapter = Column(Integer)
    
    # 关系变化历史
    change_history = Column(JSON, default=list)
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    character_a = relationship("Character", foreign_keys=[character_a_id], back_populates="relationships_as_a")
    character_b = relationship("Character", foreign_keys=[character_b_id], back_populates="relationships_as_b")
    novel = relationship("Novel", back_populates="character_relationships")

    def __repr__(self):
        return f"<Relationship {self.character_a.name} - {self.character_b.name}: {self.relationship_type}>"


class CharacterAppearance(Base):
    """角色出场记录"""
    __tablename__ = "character_appearances"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), nullable=False)
    
    # 出场类型 (main, supporting, mentioned)
    appearance_type = Column(String(20), default="supporting")
    
    # 出场描述
    description = Column(Text)
    
    # 在章节中的重要性 (1-10)
    importance_in_chapter = Column(Integer, default=5)
    
    # 角色状态变化
    status_changes = Column(JSON, default=dict)
    
    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # 关系
    character = relationship("Character", back_populates="appearances")
    chapter = relationship("Chapter", back_populates="character_appearances")

    def __repr__(self):
        return f"<Appearance {self.character.name} in Chapter {self.chapter.chapter_number}>"
