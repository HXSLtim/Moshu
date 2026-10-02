"""文风样本相关API路由"""
from typing import List
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.schemas import StyleSampleCreate, StyleSampleResponse
from app.crud import novel as novel_crud
from app.api.routes.auth import get_current_user
from app.models.user import User
from app.services.generation.style import style_service
from loguru import logger

router = APIRouter()


@router.post("/samples", response_model=StyleSampleResponse, status_code=status.HTTP_201_CREATED)
async def create_style_sample(
    request: StyleSampleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建文风样本"""
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="小说不存在或无权访问")

    # 先创建样本记录
    db_sample = novel_crud.create_style_sample(db, request)

    # 分析文风特征并更新记录
    features = style_service.analyze_style(request.sample_text)
    db_sample.style_features = json.dumps(features, ensure_ascii=False)
    db.commit()
    db.refresh(db_sample)

    logger.info(f"创建文风样本：小说{request.novel_id}，样本ID={db_sample.id}，名称={db_sample.name}")

    return StyleSampleResponse(
        id=db_sample.id,
        novel_id=db_sample.novel_id,
        name=db_sample.name,
        sample_preview=db_sample.sample_text[:100],
        style_features=features,
        created_at=db_sample.created_at,
    )


@router.get("/samples", response_model=List[StyleSampleResponse])
async def list_style_samples(
    novel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取小说下的所有文风样本"""
    novel = novel_crud.get_novel_by_id(db, novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="小说不存在或无权访问")

    samples = novel_crud.get_style_samples_by_novel(db, novel_id)
    result: List[StyleSampleResponse] = []

    for sample in samples:
        try:
            features = json.loads(sample.style_features) if sample.style_features else []
        except Exception:
            features = []

        result.append(
            StyleSampleResponse(
                id=sample.id,
                novel_id=sample.novel_id,
                name=sample.name,
                sample_preview=sample.sample_text[:100],
                style_features=features,
                created_at=sample.created_at,
            )
        )

    return result
