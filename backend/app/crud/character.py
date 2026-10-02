"""
角色管理CRUD操作
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc
from app.models.character import Character, CharacterRelationship, CharacterAppearance
from app.models.character_schemas import (
    CharacterCreate, CharacterUpdate,
    CharacterRelationshipCreate, CharacterRelationshipUpdate,
    CharacterAppearanceCreate
)
from datetime import datetime


# ========== 角色CRUD ==========

def create_character(
    db: Session,
    character: CharacterCreate,
    *,
    commit: bool = True,
) -> Character:
    """创建角色；组合业务可延迟提交以保证跨步骤原子性。"""
    db_character = Character(
        novel_id=character.novel_id,
        name=character.name,
        age=character.age,
        gender=character.gender,
        occupation=character.occupation,
        appearance=character.appearance,
        personality=character.personality,
        background=character.background,
        skills=character.skills or [],
        relationships=character.relationships or {},
        character_arc=character.character_arc,
        importance_level=character.importance_level,
        first_appearance_chapter=character.first_appearance_chapter,
    )
    db.add(db_character)
    if commit:
        db.commit()
        db.refresh(db_character)
    else:
        db.flush()
    return db_character


def get_character(db: Session, character_id: int) -> Optional[Character]:
    """获取单个角色"""
    return db.query(Character).filter(Character.id == character_id).first()


def get_characters_by_novel(
    db: Session, 
    novel_id: int, 
    skip: int = 0, 
    limit: int = 100,
    importance_level: Optional[str] = None
) -> List[Character]:
    """获取小说的所有角色"""
    query = db.query(Character).filter(Character.novel_id == novel_id)
    
    if importance_level:
        query = query.filter(Character.importance_level == importance_level)
    
    return query.offset(skip).limit(limit).all()


def get_character_by_name(db: Session, novel_id: int, name: str) -> Optional[Character]:
    """根据姓名获取角色"""
    return db.query(Character).filter(
        and_(Character.novel_id == novel_id, Character.name == name)
    ).first()


def update_character(
    db: Session, 
    character_id: int, 
    character_update: CharacterUpdate
) -> Optional[Character]:
    """更新角色"""
    db_character = get_character(db, character_id)
    if not db_character:
        return None
    
    update_data = character_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_character, field, value)
    
    db_character.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_character)
    return db_character


def delete_character(db: Session, character_id: int) -> bool:
    """删除角色"""
    db_character = get_character(db, character_id)
    if not db_character:
        return False
    
    # 聚合关系统一负责级联，避免直接删角色和删除整本小说采用不同清理规则。
    db.delete(db_character)
    db.commit()
    return True


def update_character_ai_analysis(
    db: Session, 
    character_id: int, 
    analysis: Dict[str, Any],
    *,
    commit: bool = True,
) -> Optional[Character]:
    """更新角色的AI分析结果；组合业务可与角色创建一并提交。"""
    db_character = get_character(db, character_id)
    if not db_character:
        return None
    
    db_character.ai_analysis = analysis
    db_character.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(db_character)
    return db_character


# ========== 角色关系CRUD ==========

def create_character_relationship(
    db: Session, 
    relationship: CharacterRelationshipCreate
) -> CharacterRelationship:
    """创建角色关系"""
    db_relationship = CharacterRelationship(
        novel_id=relationship.novel_id,
        character_a_id=relationship.character_a_id,
        character_b_id=relationship.character_b_id,
        relationship_type=relationship.relationship_type,
        description=relationship.description,
        strength=relationship.strength,
        development_stage=relationship.development_stage,
        established_in_chapter=relationship.established_in_chapter,
        change_history=[]
    )
    db.add(db_relationship)
    db.commit()
    db.refresh(db_relationship)
    return db_relationship


def get_character_relationships(
    db: Session, 
    character_id: int
) -> List[CharacterRelationship]:
    """获取角色的所有关系"""
    return db.query(CharacterRelationship).options(
        joinedload(CharacterRelationship.character_a),
        joinedload(CharacterRelationship.character_b)
    ).filter(
        or_(
            CharacterRelationship.character_a_id == character_id,
            CharacterRelationship.character_b_id == character_id
        )
    ).all()


def get_novel_relationships(db: Session, novel_id: int) -> List[CharacterRelationship]:
    """获取小说的所有角色关系"""
    return db.query(CharacterRelationship).options(
        joinedload(CharacterRelationship.character_a),
        joinedload(CharacterRelationship.character_b)
    ).filter(CharacterRelationship.novel_id == novel_id).all()


def update_character_relationship(
    db: Session,
    relationship_id: int,
    relationship_update: CharacterRelationshipUpdate
) -> Optional[CharacterRelationship]:
    """更新角色关系"""
    db_relationship = db.query(CharacterRelationship).filter(
        CharacterRelationship.id == relationship_id
    ).first()
    
    if not db_relationship:
        return None
    
    # 记录变更历史
    old_data = {
        "relationship_type": db_relationship.relationship_type,
        "strength": db_relationship.strength,
        "development_stage": db_relationship.development_stage,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    update_data = relationship_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_relationship, field, value)
    
    # 更新变更历史
    if not db_relationship.change_history:
        db_relationship.change_history = []
    db_relationship.change_history.append(old_data)
    
    db_relationship.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_relationship)
    return db_relationship


def delete_character_relationship(db: Session, relationship_id: int) -> bool:
    """删除角色关系"""
    db_relationship = db.query(CharacterRelationship).filter(
        CharacterRelationship.id == relationship_id
    ).first()
    
    if not db_relationship:
        return False
    
    db.delete(db_relationship)
    db.commit()
    return True


# ========== 角色出场记录CRUD ==========

def create_character_appearance(
    db: Session,
    appearance: CharacterAppearanceCreate,
    commit: bool = True,
) -> CharacterAppearance:
    """创建角色出场记录。

    调用方需要把出场与后续写入绑成同一事务时传 commit=False(自行负责提交)。
    """
    db_appearance = CharacterAppearance(
        character_id=appearance.character_id,
        chapter_id=appearance.chapter_id,
        appearance_type=appearance.appearance_type,
        description=appearance.description,
        importance_in_chapter=appearance.importance_in_chapter,
        status_changes=appearance.status_changes or {}
    )
    db.add(db_appearance)
    if commit:
        db.commit()
        db.refresh(db_appearance)
    else:
        db.flush()
    return db_appearance


def get_character_appearances(
    db: Session, 
    character_id: int
) -> List[CharacterAppearance]:
    """获取角色的所有出场记录"""
    return db.query(CharacterAppearance).options(
        joinedload(CharacterAppearance.chapter)
    ).filter(
        CharacterAppearance.character_id == character_id
    ).order_by(CharacterAppearance.chapter_id).all()


def get_chapter_characters(db: Session, chapter_id: int) -> List[CharacterAppearance]:
    """获取章节中的所有角色"""
    return db.query(CharacterAppearance).options(
        joinedload(CharacterAppearance.character)
    ).filter(
        CharacterAppearance.chapter_id == chapter_id
    ).order_by(desc(CharacterAppearance.importance_in_chapter)).all()


def update_character_last_appearance(
    db: Session,
    character_id: int,
    chapter_number: int,
    commit: bool = True,
) -> Optional[Character]:
    """更新角色最后出现章节(与出场记录绑成同一事务时传 commit=False)"""
    db_character = get_character(db, character_id)
    if not db_character:
        return None

    db_character.last_appearance_chapter = chapter_number
    db_character.updated_at = datetime.utcnow()
    if commit:
        db.commit()
        db.refresh(db_character)
    else:
        db.flush()
    return db_character


# ========== 高级查询 ==========

def search_characters(
    db: Session,
    novel_id: int,
    search_term: str,
    search_fields: List[str] = None
) -> List[Character]:
    """搜索角色"""
    if not search_fields:
        search_fields = ["name", "occupation", "personality", "background"]
    
    query = db.query(Character).filter(Character.novel_id == novel_id)
    
    conditions = []
    for field in search_fields:
        if hasattr(Character, field):
            column = getattr(Character, field)
            conditions.append(column.ilike(f"%{search_term}%"))
    
    if conditions:
        query = query.filter(or_(*conditions))
    
    return query.all()


def get_character_network(db: Session, novel_id: int) -> Dict[str, Any]:
    """获取角色关系网络"""
    characters = get_characters_by_novel(db, novel_id)
    relationships = get_novel_relationships(db, novel_id)
    
    # 构建网络图数据
    nodes = []
    edges = []
    
    for char in characters:
        nodes.append({
            "id": char.id,
            "name": char.name,
            "importance_level": char.importance_level,
            "appearance_count": len(get_character_appearances(db, char.id))
        })
    
    for rel in relationships:
        edges.append({
            "source": rel.character_a_id,
            "target": rel.character_b_id,
            "relationship_type": rel.relationship_type,
            "strength": rel.strength
        })
    
    return {
        "nodes": nodes,
        "edges": edges,
        "statistics": {
            "total_characters": len(characters),
            "total_relationships": len(relationships),
            "main_characters": len([c for c in characters if c.importance_level == "main"]),
            "secondary_characters": len([c for c in characters if c.importance_level == "secondary"])
        }
    }
