"""Story Bible 路由:事实账本与剧情事件。

所有端点按小说归属做所有权校验(404 统一),事实与事件都是
作者确认后的正式数据,不属于 AI 候选内容。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.crud import novel as novel_crud
from app.crud import story_bible as story_bible_crud
from app.db.base import get_db
from app.models.story_bible_schemas import (
    EventCreate,
    EventResponse,
    EventUpdate,
    FactCreate,
    FactResponse,
    FactUpdate,
)
from app.models.user import User
from loguru import logger

router = APIRouter()


def _require_owned_novel(db: Session, current_user: User, novel_id: int):
    """校验小说存在且属于当前用户,否则统一 404。"""
    novel = novel_crud.get_novel_by_id(db, novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在或无权访问",
        )
    return novel


# ========== 事实账本 ==========

@router.post("/facts", response_model=FactResponse, status_code=status.HTTP_201_CREATED)
async def create_fact(
    request: FactCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建故事事实。"""
    _require_owned_novel(db, current_user, request.novel_id)
    fact = story_bible_crud.create_fact(db, request)
    logger.info(f"创建事实: {fact.subject}.{fact.attribute} (novel_id={fact.novel_id})")
    return fact


@router.get("/facts", response_model=List[FactResponse])
async def list_facts(
    novel_id: int = Query(..., gt=0),
    status_filter: Optional[str] = Query(None, pattern="^(active|retired)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取小说的事实列表,可按状态过滤。"""
    _require_owned_novel(db, current_user, novel_id)
    return story_bible_crud.get_facts_by_novel(db, novel_id, status_filter, skip, limit)


@router.get("/facts/{fact_id}", response_model=FactResponse)
async def get_fact(
    fact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单条事实。"""
    fact = story_bible_crud.get_fact(db, fact_id)
    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事实不存在")
    _require_owned_novel(db, current_user, fact.novel_id)
    return fact


@router.put("/facts/{fact_id}", response_model=FactResponse)
async def update_fact(
    fact_id: int,
    request: FactUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新事实(支持 active/retired 状态流转)。"""
    fact = story_bible_crud.get_fact(db, fact_id)
    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事实不存在")
    _require_owned_novel(db, current_user, fact.novel_id)
    try:
        updated = story_bible_crud.update_fact(db, fact_id, request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return updated


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除事实。"""
    fact = story_bible_crud.get_fact(db, fact_id)
    if not fact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事实不存在")
    _require_owned_novel(db, current_user, fact.novel_id)
    try:
        story_bible_crud.delete_fact(db, fact_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ========== 剧情事件 ==========

@router.post("/events", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    request: EventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建剧情事件。"""
    _require_owned_novel(db, current_user, request.novel_id)
    event = story_bible_crud.create_event(db, request)
    logger.info(f"创建事件: {event.title} (novel_id={event.novel_id})")
    return event


@router.get("/events", response_model=List[EventResponse])
async def list_events(
    novel_id: int = Query(..., gt=0),
    status_filter: Optional[str] = Query(None, pattern="^(planned|occurred)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取小说的事件列表,按故事天数排序。"""
    _require_owned_novel(db, current_user, novel_id)
    return story_bible_crud.get_events_by_novel(db, novel_id, status_filter, skip, limit)


@router.get("/events/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取单个事件。"""
    event = story_bible_crud.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事件不存在")
    _require_owned_novel(db, current_user, event.novel_id)
    return event


@router.put("/events/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: int,
    request: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新事件。"""
    event = story_bible_crud.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事件不存在")
    _require_owned_novel(db, current_user, event.novel_id)
    try:
        return story_bible_crud.update_event(db, event_id, request)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除事件。"""
    event = story_bible_crud.get_event(db, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事件不存在")
    _require_owned_novel(db, current_user, event.novel_id)
    story_bible_crud.delete_event(db, event_id)
