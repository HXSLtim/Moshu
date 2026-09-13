"""作品内的大纲、实体和作者状态确认 API。"""
from uuid import UUID
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models.story_memory_schemas import EntityInput, OutlineInput, StateInput, DecisionInput, ResolveInput, ExtractionInput
from app.services import story_memory as memory
from app.services.story_memory_extractor import story_memory_extractor
from app.services.model_result import ModelOutputError
from app.models.story_memory import StoryEntity, StoryMemoryCommand, StoryMemoryHead

router = APIRouter(prefix="/novels/{novel_id}/story-memory")


def _run(db, novel_id, user, data, action, operation):
    try:
        return memory.execute_command(db, novel_id, user.id, data, action, operation)
    except memory.MemoryScopeError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (memory.MemoryConflict, IntegrityError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "并发修改冲突，请刷新后重试") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("")
def get_memory(novel_id: int, chapter: int | None = Query(None, gt=0),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        novel = memory.owned_novel(db, novel_id, user.id)
        return memory.snapshot(db, novel, chapter)
    except memory.MemoryScopeError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/entities")
def create_entity(novel_id: int, data: EntityInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, "create_entity", lambda novel: memory.create_entity(db, novel, data))


@router.post("/outline")
def create_outline(novel_id: int, data: OutlineInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, "create_outline", lambda novel: memory.save_outline(db, novel, data))


@router.put("/outline/{node_id}")
def update_outline(novel_id: int, node_id: UUID, data: OutlineInput,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, f"update_outline:{node_id}", lambda novel: memory.save_outline(db, novel, data, node_id))


@router.post("/states")
def create_state(novel_id: int, data: StateInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, "create_state", lambda novel: memory.create_state(db, novel, data))


@router.post("/states/{fact_id}/replace")
def replace_state(novel_id: int, fact_id: int, data: StateInput,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, f"replace_state:{fact_id}", lambda novel: memory.replace_state(db, novel, fact_id, data))


@router.post("/candidates")
def create_candidate(novel_id: int, data: StateInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, "create_candidate", lambda novel: memory.create_candidate(db, novel, data))


@router.post("/candidates/{candidate_id}/decision")
def decide(novel_id: int, candidate_id: UUID, data: DecisionInput,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, f"decide:{candidate_id}", lambda novel: memory.decide_candidate(db, novel, candidate_id, data))


@router.post("/states/{fact_id}/resolve")
def resolve_state(novel_id: int, fact_id: int, data: ResolveInput,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, f"resolve_state:{fact_id}", lambda novel: memory.resolve_source(db, novel, "state", fact_id, data))


@router.post("/outline/{node_id}/resolve")
def resolve_outline(novel_id: int, node_id: UUID, data: ResolveInput,
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _run(db, novel_id, user, data, f"resolve_outline:{node_id}", lambda novel: memory.resolve_source(db, novel, "outline", node_id, data))


@router.post("/extract")
def extract(novel_id: int, data: ExtractionInput,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from types import SimpleNamespace
    try:
        novel = memory.owned_novel(db, novel_id, user.id)
        if novel.rag_lifecycle_id != data.novel_lifecycle_id:
            raise memory.MemoryScopeError("作品生命周期已变化")
        existing = db.query(StoryMemoryCommand).filter_by(novel_lifecycle_id=novel.rag_lifecycle_id,
            request_id=str(data.request_id)).first()
        if existing:
            return _run(db, novel_id, user, data, "extract", lambda _: None)
        head = db.get(StoryMemoryHead, novel.id)
        if data.expected_version != (head.version if head else 0):
            raise memory.MemoryConflict("记忆已被更新，请刷新后重新提取")
        revision = memory.source_revision(db, novel, data.source_revision_id)
        frozen = SimpleNamespace(id=revision.id, content=revision.content)
        entities = [SimpleNamespace(id=row.id, name=row.name, description=row.description, kind=row.kind) for row in db.query(StoryEntity).filter_by(
            novel_id=novel.id, novel_lifecycle_id=novel.rag_lifecycle_id).limit(41)]
        db.commit()
        # 同步路由在线程池中完成数据库操作；模型等待期间释放事务，不阻塞应用事件循环。
        result = asyncio.run(story_memory_extractor.extract(frozen, entities))
        return _run(db, novel_id, user, data, "extract", lambda current: memory.publish_extraction(db, current, frozen.id, result))
    except memory.MemoryScopeError as exc:
        raise HTTPException(404, str(exc)) from exc
    except memory.MemoryConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, ModelOutputError) as exc:
        raise HTTPException(422, "结构化提取或来源校验失败，请检查原文版本及模型输出") from exc
    except TimeoutError as exc:
        raise HTTPException(504, "结构化提取超时，未修改正式状态") from exc
