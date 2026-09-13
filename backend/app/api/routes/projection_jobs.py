"""作者可以查看并重试自己的持久投影，包括已删除作品的清理任务。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.dependencies import get_current_user
from app.db.base import get_db
from app.models.projection_job import ProjectionJob
from app.models.memory import utc_now
from app.models.user import User

router = APIRouter()


def response(job):
    return {key: getattr(job, key) for key in ('id', 'novel_id', 'kind', 'state', 'attempts', 'max_attempts', 'error', 'created_at')}


@router.get('/projection-jobs')
def list_jobs(novel_id: int = Query(..., gt=0), limit: int = Query(50, ge=1, le=100),
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ProjectionJob).filter_by(novel_id=novel_id, actor_id=user.id).order_by(ProjectionJob.created_at.desc()).limit(limit).all()
    return [response(row) for row in rows]


@router.post('/projection-jobs/{job_id}/retry')
def retry_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(ProjectionJob).filter_by(id=job_id, actor_id=user.id).first()
    if row is None:
        raise HTTPException(404, '投影任务不存在或无权访问')
    db.query(ProjectionJob).filter_by(id=row.id, actor_id=user.id, state='failed').update(
        {'state': 'queued', 'attempts': 0, 'error': None, 'available_at': utc_now()}, synchronize_session=False)
    db.commit()
    db.refresh(row)
    return response(row)
