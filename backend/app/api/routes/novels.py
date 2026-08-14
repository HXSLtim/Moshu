"""
小说和章节管理API路由
"""
from typing import List
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.schemas import (
    NovelCreate,
    NovelUpdate,
    NovelResponse,
    NovelStatisticsResponse,
    ChapterCreate,
    ChapterNextCreate,
    ChapterPageResponse,
    ChapterUpdate,
    ChapterResponse,
)
from app.crud import novel as novel_crud
from app.api.dependencies import get_current_user
from app.services.rag_service import rag_service
from loguru import logger

router = APIRouter()


async def _index_projection(**kwargs) -> None:
    """执行后台索引并显式记录结果，避免布尔失败被误报为成功。"""
    indexed = await rag_service.index_content(**kwargs)
    if indexed:
        logger.info(
            "RAG后台索引完成：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )
    elif not settings.EMBEDDING_ENABLED:
        logger.info(
            "RAG后台索引已按配置跳过：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )
    else:
        logger.warning(
            "RAG后台索引失败：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )


async def _cleanup_chapter_projection(
    novel_id: int,
    chapter_id: int,
    deletion_token: dict,
) -> None:
    """幂等清理章节派生索引。"""
    cleaned = await rag_service.cleanup_chapter_data(
        novel_id,
        chapter_id,
        deletion_token=deletion_token,
    )
    if not cleaned:
        logger.warning("章节RAG后台清理失败：novel_id={}, chapter_id={}", novel_id, chapter_id)


async def _cleanup_novel_projection(novel_id: int, deletion_token: dict) -> None:
    """幂等清理小说派生索引。"""
    await rag_service.cleanup_novel_vectors(
        novel_id,
        deletion_token=deletion_token,
    )


def _worldview_projection_version(novel) -> int:
    """返回由数据库原子递增的世界观投影版本。"""
    return int(novel.rag_revision or 1)


# ========== Novel 路由 ==========

@router.post("/", response_model=NovelResponse, status_code=status.HTTP_201_CREATED)
async def create_novel(
    novel: NovelCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建小说

    需要认证
    """
    db_novel = novel_crud.create_novel(db, novel, user_id=current_user.id)
    rag_service.prepare_novel_projection(db_novel.id, db=db)
    if novel.worldview is not None:
        projection_token = rag_service.prepare_worldview_projection(db_novel.id, db=db)
        background_tasks.add_task(
            _index_projection,
            novel_id=db_novel.id,
            chapter=0,
            content=db_novel.worldview or "",
            metadata={
                "source": "worldview",
                "version": _worldview_projection_version(db_novel),
                **projection_token,
            },
        )
    return db_novel


@router.get("/", response_model=List[NovelResponse])
async def list_my_novels(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取当前用户的所有小说

    需要认证
    """
    novels = novel_crud.get_novels_by_user(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )
    return novels


@router.get("/statistics", response_model=NovelStatisticsResponse)
async def get_my_novel_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用一次聚合查询返回当前用户全部小说的章节数和总字数。"""
    return NovelStatisticsResponse(
        items=novel_crud.get_novel_statistics_by_user(db, current_user.id)
    )


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(
    novel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取小说详情

    需要认证，只能查看自己的小说
    """
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限：只能查看自己的小说
    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此小说"
        )

    return db_novel


@router.put("/{novel_id}", response_model=NovelResponse)
async def update_novel(
    novel_id: int,
    novel_update: NovelUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新小说信息

    需要认证，只能更新自己的小说
    """
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限
    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改此小说"
        )

    updated_novel = novel_crud.update_novel(db, novel_id, novel_update)

    # 世界观索引是可重建投影，不阻塞数据库更新响应。
    if novel_update.worldview is not None:
        projection_token = rag_service.prepare_worldview_projection(
            updated_novel.id,
            db=db,
        )
        background_tasks.add_task(
            _index_projection,
            novel_id=updated_novel.id,
            chapter=0,
            content=updated_novel.worldview or "",
            metadata={
                "source": "worldview",
                "version": _worldview_projection_version(updated_novel),
                **projection_token,
            },
        )

    return updated_novel


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_novel(
    novel_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除小说（级联删除所有章节）

    需要认证，只能删除自己的小说
    """
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    # 验证权限
    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除此小说"
        )

    # 删除提交前捕获持久生命周期；提交后同一整数主键可能已属于另一位作者。
    deletion_token = rag_service.mark_novel_deleted(novel_id, db=db)
    if not novel_crud.delete_novel(db, novel_id):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除小说失败",
        )
    background_tasks.add_task(_cleanup_novel_projection, novel_id, deletion_token)
    return None


# ========== Chapter 路由 ==========

@router.post("/{novel_id}/chapters", response_model=ChapterResponse, status_code=status.HTTP_201_CREATED)
async def create_chapter(
    novel_id: int,
    chapter: ChapterCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    创建章节

    需要认证，只能为自己的小说创建章节
    """
    # 验证小说存在且有权限
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权为此小说添加章节"
        )

    # 检查章节号是否已存在
    existing_chapter = novel_crud.get_chapter_by_number(
        db,
        novel_id,
        chapter.chapter_number
    )
    if existing_chapter:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"章节 {chapter.chapter_number} 已存在"
        )

    try:
        db_chapter = novel_crud.create_chapter(db, novel_id, chapter)
    except novel_crud.ChapterNumberConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    projection_token = rag_service.prepare_chapter_projection(
        novel_id,
        db_chapter.id,
        db=db,
    )
    background_tasks.add_task(
        _index_projection,
        novel_id=novel_id,
        chapter=db_chapter.chapter_number,
        content=db_chapter.content,
        metadata={
            "source": "chapter",
            "chapter_id": db_chapter.id,
            "version": db_chapter.version,
            **projection_token,
        },
    )

    return db_chapter


@router.post(
    "/{novel_id}/chapters/next",
    response_model=ChapterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_next_chapter(
    novel_id: int,
    chapter: ChapterNextCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """由服务端原子分配当前最大章节号的下一号。"""
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="小说不存在")
    if db_novel.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权为此小说添加章节")

    try:
        db_chapter = novel_crud.create_next_chapter(db, novel_id, chapter)
    except novel_crud.ChapterNumberConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    projection_token = rag_service.prepare_chapter_projection(
        novel_id,
        db_chapter.id,
        db=db,
    )
    background_tasks.add_task(
        _index_projection,
        novel_id=novel_id,
        chapter=db_chapter.chapter_number,
        content=db_chapter.content,
        metadata={
            "source": "chapter",
            "chapter_id": db_chapter.id,
            "version": db_chapter.version,
            **projection_token,
        },
    )
    return db_chapter


@router.get("/{novel_id}/chapters", response_model=ChapterPageResponse)
async def list_chapters(
    novel_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取小说的所有章节

    需要认证，只能查看自己小说的章节
    """
    # 验证小说存在且有权限
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此小说的章节"
        )

    skip = (page - 1) * page_size
    chapters = novel_crud.get_chapters_by_novel(
        db,
        novel_id,
        skip=skip,
        limit=page_size,
    )
    total = novel_crud.count_chapters_by_novel(db, novel_id)
    return ChapterPageResponse(
        items=chapters,
        total=total,
        page=page,
        page_size=page_size,
        has_more=skip + len(chapters) < total,
    )


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(
    novel_id: int,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取章节详情

    需要认证，只能查看自己小说的章节
    """
    # 验证小说存在且有权限
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此小说的章节"
        )

    db_chapter = novel_crud.get_chapter_by_id(db, chapter_id)
    if not db_chapter or db_chapter.novel_id != novel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )

    return db_chapter


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    novel_id: int,
    chapter_id: int,
    chapter_update: ChapterUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    更新章节

    需要认证，只能更新自己小说的章节
    """
    # 验证小说存在且有权限
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权修改此小说的章节"
        )

    db_chapter = novel_crud.get_chapter_by_id(db, chapter_id)
    if not db_chapter or db_chapter.novel_id != novel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )

    try:
        updated_chapter = novel_crud.update_chapter(db, chapter_id, chapter_update)
    except novel_crud.ChapterVersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"章节已被其他保存更新，当前版本为{exc.current_version}，请刷新后重试",
        ) from exc
    except novel_crud.ChapterNumberConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if updated_chapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")

    # 只有正文或章节号变化才需要刷新向量投影；保存响应不等待投影完成。
    if chapter_update.content is not None or chapter_update.chapter_number is not None:
        projection_token = rag_service.prepare_chapter_projection(
            novel_id,
            updated_chapter.id,
            db=db,
        )
        background_tasks.add_task(
            _index_projection,
            novel_id=novel_id,
            chapter=updated_chapter.chapter_number,
            content=updated_chapter.content,
            metadata={
                "source": "chapter",
                "chapter_id": updated_chapter.id,
                "version": updated_chapter.version,
                **projection_token,
            },
        )
    return updated_chapter


@router.delete("/{novel_id}/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(
    novel_id: int,
    chapter_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除章节

    需要认证，只能删除自己小说的章节
    """
    # 验证小说存在且有权限
    db_novel = novel_crud.get_novel_by_id(db, novel_id)
    if not db_novel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )

    if db_novel.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除此小说的章节"
        )

    db_chapter = novel_crud.get_chapter_by_id(db, chapter_id)
    if not db_chapter or db_chapter.novel_id != novel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="章节不存在"
        )

    # 同小说内章节主键也可能复用，必须在删除前冻结来源生命周期。
    deletion_token = rag_service.mark_chapter_deleted(novel_id, chapter_id, db=db)
    success = novel_crud.delete_chapter(db, chapter_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除章节失败"
        )
    background_tasks.add_task(
        _cleanup_chapter_projection,
        novel_id,
        chapter_id,
        deletion_token,
    )
    return None
