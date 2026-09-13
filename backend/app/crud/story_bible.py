"""Story Bible(事实与事件)CRUD 操作。"""

from typing import List, Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.story_bible import StoryEvent, StoryFact
from app.models.story_bible_schemas import EventCreate, EventUpdate, FactCreate, FactUpdate
from app.models.novel import Novel


# ========== 故事事实 CRUD ==========

def create_fact(db: Session, fact: FactCreate, *, commit: bool = True) -> StoryFact:
    """创建故事事实,状态固定从 active 开始。"""
    novel = db.get(Novel, fact.novel_id)
    if novel is None or not novel.rag_lifecycle_id:
        raise ValueError("事实所属小说不存在或生命周期不可用")
    db_fact = StoryFact(
        novel_id=fact.novel_id,
        novel_lifecycle_id=novel.rag_lifecycle_id,
        subject=fact.subject,
        attribute=fact.attribute,
        value=fact.value,
        description=fact.description,
        chapter_established=fact.chapter_established,
        status="active",
    )
    db.add(db_fact)
    if commit:
        db.commit()
        db.refresh(db_fact)
    else:
        db.flush()
    return db_fact


def get_fact(db: Session, fact_id: int) -> Optional[StoryFact]:
    """获取单条事实。"""
    return db.query(StoryFact).filter(StoryFact.id == fact_id).first()


def get_facts_by_novel(
    db: Session,
    novel_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[StoryFact]:
    """获取小说的事实列表,可按状态过滤。"""
    query = db.query(StoryFact).filter(StoryFact.novel_id == novel_id)
    if status:
        query = query.filter(StoryFact.status == status)
    return query.order_by(StoryFact.id).offset(skip).limit(limit).all()


def get_active_facts_for_generation(
    db: Session,
    novel_id: int,
    max_chapter: Optional[int] = None,
    limit: int = 40,
    *,
    include_structured: bool = True,
    novel_lifecycle_id: str | None = None,
    diagnostics: dict | None = None,
) -> List[StoryFact]:
    """按目标章节读取当时有效的事实；无目标章节时读取当前有效事实。"""
    query = db.query(StoryFact).filter(StoryFact.novel_id == novel_id)
    if novel_lifecycle_id:
        # 旧迁移允许 lifecycle 为空，但空值无法证明它属于当前同 ID 作品；
        # 生成上下文中默认排除，并把待回填数量交给调用方显示。
        unscoped = query.filter(StoryFact.novel_lifecycle_id.is_(None)).count()
        if unscoped and diagnostics is not None:
            diagnostics["legacy_unscoped_fact"] = unscoped
        query = query.filter(StoryFact.novel_lifecycle_id == novel_lifecycle_id)
    if max_chapter is not None:
        query = query.filter(
            or_(
                StoryFact.status == "active",
                and_(StoryFact.status == "retired", StoryFact.retired_chapter > max_chapter),
            ),
            or_(
                StoryFact.chapter_established.is_(None),
                StoryFact.chapter_established <= max_chapter,
            )
        )
    else:
        query = query.filter(StoryFact.status == "active")
    # 实体状态由同一 StoryFact 真源的来源链校验器按章选取，不能从旧入口绕过待核对标记。
    legacy = query.filter(StoryFact.entity_id.is_(None), StoryFact.source_status == "ready").order_by(StoryFact.id).limit(limit).all()
    if not include_structured:
        return legacy
    from app.services.story_memory import get_valid_core_facts
    target = max_chapter if max_chapter is not None else 2_147_483_647
    structured = get_valid_core_facts(db, novel_id, target, limit=limit)
    return (structured + legacy)[:limit]


def update_fact(db: Session, fact_id: int, update: FactUpdate) -> Optional[StoryFact]:
    """更新事实;状态流转时同步记录失效章节。"""
    db_fact = get_fact(db, fact_id)
    if not db_fact:
        return None

    data = update.model_dump(exclude_unset=True)
    if db_fact.entity_id is not None:
        raise ValueError("结构化实体状态须使用状态审阅命令修改，不能绕过版本和来源记录")
    if data.get("status") == "retired" and "retired_chapter" not in data and db_fact.retired_chapter is None:
        # 未指定失效章节时,默认沿用确立章节,保持账本可追溯。
        data["retired_chapter"] = db_fact.chapter_established

    value = data.get("value", db_fact.value)
    state = data.get("status", db_fact.status)
    established = data.get("chapter_established", db_fact.chapter_established)
    retired = data.get("retired_chapter", db_fact.retired_chapter)
    if value is None or not value.strip() or state not in {"active", "retired"}:
        raise ValueError("事实值和状态不能为空")
    if established is not None and retired is not None and retired < established:
        raise ValueError("事实失效章节不能早于确立章节")

    for field, value in data.items():
        setattr(db_fact, field, value)

    db.commit()
    db.refresh(db_fact)
    return db_fact


def delete_fact(db: Session, fact_id: int) -> bool:
    """删除事实。"""
    db_fact = get_fact(db, fact_id)
    if not db_fact:
        return False
    if db_fact.entity_id is not None:
        raise ValueError("结构化实体状态须撤销或替换，不能删除来源历史")
    db.delete(db_fact)
    db.commit()
    return True


# ========== 剧情事件 CRUD ==========

def create_event(db: Session, event: EventCreate, *, commit: bool = True) -> StoryEvent:
    """创建剧情事件。"""
    db_event = StoryEvent(
        novel_id=event.novel_id,
        title=event.title,
        description=event.description,
        story_day=event.story_day,
        chapter=event.chapter,
        involved_characters=event.involved_characters or [],
        foreshadowing=event.foreshadowing,
        status=event.status or "planned",
    )
    db.add(db_event)
    if commit:
        db.commit()
        db.refresh(db_event)
    else:
        db.flush()
    return db_event


def get_event(db: Session, event_id: int) -> Optional[StoryEvent]:
    """获取单个事件。"""
    return db.query(StoryEvent).filter(StoryEvent.id == event_id).first()


def get_events_by_novel(
    db: Session,
    novel_id: int,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[StoryEvent]:
    """获取小说的事件列表,按故事天数排序。"""
    query = (
        db.query(StoryEvent)
        .filter(StoryEvent.novel_id == novel_id)
        .order_by(StoryEvent.story_day, StoryEvent.id)
    )
    if status:
        query = query.filter(StoryEvent.status == status)
    return query.offset(skip).limit(limit).all()


def get_events_for_generation(
    db: Session,
    novel_id: int,
    max_chapter: Optional[int] = None,
    current_day: Optional[int] = None,
    limit: int = 20,
) -> List[StoryEvent]:
    """只取已发生且不晚于目标位置的事件，规划事件不能充当正式剧情。"""
    query = db.query(StoryEvent).filter(
        StoryEvent.novel_id == novel_id, StoryEvent.status == "occurred",
    )
    if max_chapter is not None:
        if current_day is None:
            # 无目标日时，不能判断无章节事件在旧章是否已经发生。
            query = query.filter(StoryEvent.chapter <= max_chapter)
        else:
            query = query.filter(
                or_(
                    StoryEvent.chapter.is_(None),
                    StoryEvent.chapter <= max_chapter,
                )
            )
    if current_day is not None:
        query = query.filter(StoryEvent.story_day <= current_day)
    return (
        query.order_by(StoryEvent.story_day.desc(), StoryEvent.id.desc())
        .limit(limit)
        .all()
    )


def update_event(db: Session, event_id: int, update: EventUpdate) -> Optional[StoryEvent]:
    """更新事件。"""
    db_event = get_event(db, event_id)
    if not db_event:
        return None

    data = update.model_dump(exclude_unset=True)
    merged = {field: data.get(field, getattr(db_event, field)) for field in (
        "title", "description", "story_day", "status", "involved_characters",
    )}
    if (not isinstance(merged["title"], str) or not merged["title"].strip()
            or not isinstance(merged["description"], str) or not merged["description"].strip()
            or type(merged["story_day"]) is not int or merged["story_day"] <= 0
            or merged["status"] not in {"planned", "occurred"}
            or not isinstance(merged["involved_characters"], list)):
        raise ValueError("事件标题、描述、故事日、状态和角色列表必须是有效值，不能设为 null")
    for field, value in data.items():
        setattr(db_event, field, value)

    db.commit()
    db.refresh(db_event)
    return db_event


def delete_event(db: Session, event_id: int) -> bool:
    """删除事件。"""
    db_event = get_event(db, event_id)
    if not db_event:
        return False
    db.delete(db_event)
    db.commit()
    return True
