"""章节审核API路由"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Annotated, List, Optional
from loguru import logger
from app.services.review_agent_service import review_agent_service
from app.services.context_budget import MAX_CURRENT_CONTENT_CHARS
from app.api.dependencies import get_current_user
from app.crud import novel as novel_crud
from app.db.base import get_db
from app.models.user import User
from sqlalchemy.orm import Session
import json
import asyncio


router = APIRouter()


ReviewPreviousChapter = Annotated[str, Field(min_length=1, max_length=20_000)]


class ChapterReviewRequest(BaseModel):
    """章节审核请求"""
    novel_id: int = Field(..., gt=0)
    chapter_id: int = Field(..., gt=0)
    chapter_number: int = Field(..., gt=0)
    content: str = Field(..., min_length=1, max_length=MAX_CURRENT_CONTENT_CHARS)
    previous_chapters: Optional[List[ReviewPreviousChapter]] = Field(
        None,
        max_length=3,
    )


def _get_owned_chapter(
    db: Session,
    current_user: User,
    request: ChapterReviewRequest,
):
    """校验审核请求中的小说与章节都属于当前用户。"""

    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="小说不存在或无权访问")
    chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
    if not chapter or chapter.novel_id != request.novel_id:
        raise HTTPException(status_code=404, detail="章节不存在或不属于该小说")
    return chapter


@router.post("/chapter")
async def review_chapter(
    request: ChapterReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    对章节进行全面审核
    
    返回综合审核结果，包括：
    - 节奏审核
    - 质量检查
    - 情节连贯性
    - 角色一致性
    - 语言风格
    - 内容安全
    """
    logger.info(f"收到章节审核请求: novel_id={request.novel_id}, chapter={request.chapter_number}")
    
    try:
        chapter = _get_owned_chapter(db, current_user, request)
        result = await review_agent_service.review_chapter_comprehensive(
            novel_id=request.novel_id,
            chapter_id=request.chapter_id,
            chapter_number=chapter.chapter_number,
            content=request.content,
            previous_chapters=request.previous_chapters,
        )
        
        logger.info(f"审核完成: 总分={result['overall_score']}, 可发布={result['is_ready_for_publish']}")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"章节审核失败: {e}")
        raise HTTPException(status_code=500, detail=f"审核失败: {str(e)}")


@router.post("/chapter-stream")
async def review_chapter_stream(
    request: ChapterReviewRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    流式章节审核
    
    实时返回各个Agent的审核进度和结果
    """
    chapter = _get_owned_chapter(db, current_user, request)
    logger.info(f"收到流式章节审核请求: novel_id={request.novel_id}, chapter={chapter.chapter_number}")
    
    async def event_generator():
        try:
            # 发送开始事件
            yield f"data: {json.dumps({'type': 'start', 'message': '开始审核'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
            
            result = await review_agent_service.review_chapter_comprehensive(
                novel_id=request.novel_id,
                chapter_id=request.chapter_id,
                chapter_number=chapter.chapter_number,
                content=request.content,
                previous_chapters=request.previous_chapters,
            )
            if await http_request.is_disconnected():
                return

            result_fields = {
                "pace": "pace_review",
                "quality": "quality_review",
                "plot": "plot_coherence",
                "character": "character_consistency",
                "style": "style_review",
                "safety": "content_safety",
            }
            for agent_name, field_name in result_fields.items():
                event = {
                    "type": "agent_result",
                    "agent": agent_name,
                    "result": result[field_name],
                }
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

            summary = {"type": "summary", **result}
            yield f"data: {json.dumps(summary, ensure_ascii=False, default=str)}\n\n"
            done_payload = {"type": "done"}
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
            logger.info(
                "流式审核完成: 总分={}, 可发布={}, 状态={}",
                result["overall_score"],
                result["is_ready_for_publish"],
                result["review_status"],
            )
        except asyncio.CancelledError:
            logger.info(
                "章节审核流已取消: novel_id={}, chapter_id={}",
                request.novel_id,
                request.chapter_id,
            )
            raise
        except Exception as e:
            logger.error(f"流式审核失败: {e}")
            error_payload = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/test")
async def test_review_route(current_user: User = Depends(get_current_user)):
    """测试审核路由是否正常工作"""
    logger.info("审核路由测试被调用")
    return {"status": "ok", "message": "审核路由工作正常"}
