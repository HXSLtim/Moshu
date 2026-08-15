"""Story Bible(事实与事件)CRUD 操作。"""

from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.story_bible import StoryEvent, StoryFact
from app.models.story_bible_schemas import EventCreate, EventUpdate, FactCreate, FactUpdate


# ========== 故事事实 CRUD ==========

def create_fact(db: Session, fact: FactCreate, *, commit: bool = True) -> StoryFact:
    """创建故事事实,状态固定从 active 开始。"""
    db_fact = StoryFact(
        novel_id=fact.novel_id,
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
    return query.offset(skip).limit(limit).all()


def get_active_facts_for_generation(
    db: Session,
    novel_id: int,
    max_chapter: Optional[int] = None,
    limit: int = 40,
) -> List[StoryFact]:
    """取当前仍有效、且不晚于目标章节确立的事实，供生成上下文使用。"""
    query = db.query(StoryFact).filter(
        StoryFact.novel_id == novel_id,
        StoryFact.status == "active",
    )
    if max_chapter is not None:
        query = query.filter(
            or_(
                StoryFact.chapter_established.is_(None),
                StoryFact.chapter_established <= max_chapter,
            )
        )
    return query.order_by(StoryFact.id).limit(limit).all()


def update_fact(db: Session, fact_id: int, update: FactUpdate) -> Optional[StoryFact]:
    """更新事实;状态流转时同步记录失效章节。"""
    db_fact = get_fact(db, fact_id)
    if not db_fact:
        return None

    data = update.model_dump(exclude_unset=True)
    if data.get("status") == "retired" and "retired_chapter" not in data and db_fact.retired_chapter is None:
        # 未指定失效章节时,默认沿用确立章节,保持账本可追溯。
        data["retired_chapter"] = db_fact.chapter_established

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
    """取不晚于目标章节与当前故事日的事件，按时间倒序供上下文裁剪。"""
    query = db.query(StoryEvent).filter(StoryEvent.novel_id == novel_id)
    if max_chapter is not None:
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
