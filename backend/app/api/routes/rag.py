"""RAG 调试相关路由

提供用于调试和可视化 RAG 检索结果的接口，只允许访问当前用户自己的小说索引。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.user import User
from app.api.dependencies import get_current_user
from app.models.schemas import RAGQuery, RAGResponse
from app.crud import novel as novel_crud
from app.services.rag_service import rag_service
from pydantic import BaseModel
from loguru import logger

router = APIRouter()


@router.post("/debug", response_model=RAGResponse)
async def rag_debug(
    request: RAGQuery,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RAGResponse:
    """RAG 调试接口

    根据给定的 novel_id 和 query 执行一次混合检索，返回原始 content、score 和 metadata，
    便于前端可视化当前模型实际检索到的上下文。
    """
    # 验证小说所有权
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在或无权访问",
        )

    try:
        response = await rag_service.hybrid_search(request, actor_id=current_user.id, novel_lifecycle_id=novel.rag_lifecycle_id)
    except ValueError as exc:
        raise HTTPException(404, "作品来源已变化") from exc
    return response


class RAGCleanupRequest(BaseModel):
    """RAG清理请求"""
    novel_id: int


class RAGCleanupResponse(BaseModel):
    """RAG清理响应"""
    success: bool
    message: str
    cleaned_items: dict


@router.post("/cleanup", response_model=RAGCleanupResponse)
async def cleanup_rag_data(
    request: RAGCleanupRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RAGCleanupResponse:
    """清理RAG向量数据
    
    清理指定小说的所有RAG相关数据，包括：
    - 向量数据库中的章节向量
    - 知识图谱数据
    - 缓存的分析结果
    """
    # 验证小说所有权
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在或无权访问",
        )

    try:
        logger.info(f"开始清理小说 {request.novel_id} 的RAG数据")
        
        # 清理向量数据库
        token = rag_service.prepare_novel_projection(request.novel_id, db=db)
        vector_count = await rag_service.cleanup_projection_strict("delete_novel", token)
        
        # 清理知识图谱（如果有的话）
        graph_count = await rag_service.cleanup_novel_graph(request.novel_id)
        
        # 清理缓存
        cache_count = await rag_service.cleanup_novel_cache(request.novel_id)
        
        cleaned_items = {
            "vectors": vector_count,
            "graph_nodes": graph_count,
            "cache_entries": cache_count,
        }
        
        logger.info(f"清理完成，清理项目: {cleaned_items}")
        
        return RAGCleanupResponse(
            success=True,
            message=f"成功清理小说 {novel.title} 的RAG数据",
            cleaned_items=cleaned_items,
        )
        
    except Exception as e:
        logger.error(f"清理RAG数据失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清理RAG数据失败: {str(e)}",
        )
