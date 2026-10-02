from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger
from app.services.review.consistency import consistency_service
from app.services.review.reference import load_consistency_reference
from app.services.context.budget import MAX_CURRENT_CONTENT_CHARS
from app.api.dependencies import get_current_user
from app.crud import novel as novel_crud
from app.db.base import get_db
from app.models.user import User
import json
import asyncio

logger.info("一致性检查路由模块正在加载...")

router = APIRouter()

logger.info("一致性检查路由器已创建")


class ConsistencyCheckRequest(BaseModel):
    novel_id: int = Field(..., gt=0)
    chapter: int = Field(..., gt=0)
    content: str = Field(..., min_length=1, max_length=MAX_CURRENT_CONTENT_CHARS)
    current_day: int | None = Field(None, gt=0, description="故事当前天数；未知时跳过按日时间线检查")


@router.get("/test")
async def test_consistency_route(current_user: User = Depends(get_current_user)):
    """测试路由是否正常工作"""
    logger.info("一致性检查测试路由被调用")
    return {"status": "ok", "message": "一致性检查路由工作正常"}


@router.post("/check-stream")
async def check_consistency_stream(
    request: ConsistencyCheckRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="小说不存在或无权访问")
    chapter = novel_crud.get_chapter_by_number(db, request.novel_id, request.chapter)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在或不属于该小说")

    reference = load_consistency_reference(db, novel_id=request.novel_id, actor_id=current_user.id,
        novel_lifecycle_id=novel.rag_lifecycle_id, chapter=request.chapter, current_day=request.current_day)
    db.commit()
    logger.info(f"收到一致性检查请求: novel_id={request.novel_id}, chapter={request.chapter}")
    async def event_generator():
        disconnected = False
        try:
            async for event in consistency_service.check_content_stream(
                novel_id=request.novel_id,
                content=request.content,
                chapter=request.chapter,
                current_day=request.current_day,
                reference=reference,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    logger.info(
                        "一致性检查流已断开: novel_id={}, chapter={}",
                        request.novel_id,
                        request.chapter,
                    )
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                await asyncio.sleep(0)
            if not disconnected:
                done_payload = {"type": "done"}
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info(
                "一致性检查流已取消: novel_id={}, chapter={}",
                request.novel_id,
                request.chapter,
            )
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"一致性检查流式接口失败: {e}")
            error_payload = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
