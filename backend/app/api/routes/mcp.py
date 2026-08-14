"""
统一 MCP 控制中心 API 路由。

能力清单以真实处理器为准，不对外承诺占位功能。
"""
from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status, Request
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.user import User
from app.models.novel import Novel
from app.models.worldview_schemas import (
    UnifiedMCPAction, UnifiedMCPResponse,
    NovelAnalysisRequest, NovelAnalysisResponse,
    NovelOptimizationRequest, NovelOptimizationResponse
)
from app.crud import novel as novel_crud
from app.api.dependencies import get_current_user
from app.services.unified_mcp_service import unified_mcp_service
from app.services.mcp_audit_service import mcp_audit_service
from loguru import logger

router = APIRouter()


@router.post("/execute", response_model=UnifiedMCPResponse)
async def execute_unified_mcp_action(
    action: UnifiedMCPAction,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    执行统一MCP操作
    
    实际可用能力以 `/capabilities` 返回的能力矩阵为准；未实现操作会明确
    返回失败，不会生成占位成功结果。
    """
    try:
        # 获取客户端信息
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        result = await unified_mcp_service.execute_unified_action(
            db, action, current_user.id, ip_address, user_agent
        )
        
        logger.info(f"统一MCP操作: {action.target_type}.{action.action} - 用户: {current_user.username}")
        
        return result
        
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"统一MCP操作失败: {action.target_type}.{action.action} - {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"操作执行失败: {str(e)}"
        )


@router.post("/analyze/novel", response_model=NovelAnalysisResponse)
async def analyze_novel_comprehensive(
    request: NovelAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    全面分析小说
    
    AI对小说进行多维度深度分析：
    - worldview: 世界观一致性和完整性
    - character: 角色深度和关系网络
    - plot: 情节结构和节奏
    - style: 文风一致性和特色
    - consistency: 整体一致性检查
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        result = await unified_mcp_service.analyze_novel_comprehensive(db, request, current_user.id)
        
        logger.info(f"小说全面分析完成: 小说ID {request.novel_id} - 用户: {current_user.username}")
        
        return result
        
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"小说分析失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {str(e)}"
        )


@router.post("/optimize/novel", response_model=NovelOptimizationResponse)
async def optimize_novel_comprehensive(
    request: NovelOptimizationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    全面优化小说
    
    AI对小说进行系统性优化：
    - 基于分析结果提供具体改进方案
    - 生成详细的实施计划
    - 评估优化影响和优先级
    - 提供可执行的优化步骤
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        result = await unified_mcp_service.optimize_novel_comprehensive(db, request, current_user.id)
        
        logger.info(f"小说全面优化完成: 小说ID {request.novel_id} - 用户: {current_user.username}")
        
        return result
        
    except HTTPException:
        raise
    except NotImplementedError as e:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"小说优化失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"优化失败: {str(e)}"
        )


@router.post("/ai-takeover/{novel_id}")
async def ai_takeover_novel(
    novel_id: Annotated[int, Path(gt=0)],
    takeover_scope: List[str],
    ai_instructions: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    AI接管小说管理
    
    让AI完全接管小说的指定方面：
    - 自动分析当前状态
    - 识别需要改进的地方
    - 制定优化计划
    - 自动执行优化操作
    - 持续监控和调整
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="AI接管尚未接入可审计、可回滚的真实执行链路",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI接管失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI接管失败: {str(e)}"
        )


@router.post("/ai-autopilot/{novel_id}")
async def enable_ai_autopilot(
    novel_id: Annotated[int, Path(gt=0)],
    autopilot_config: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    启用AI自动驾驶模式
    
    AI将持续监控和管理小说：
    - 自动检测问题和改进机会
    - 主动提出优化建议
    - 在授权范围内自动执行改进
    - 定期生成管理报告
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="AI自动驾驶尚未实现任务调度、持久化和回滚能力",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI自动驾驶启用失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启用失败: {str(e)}"
        )


@router.get("/capabilities")
async def get_mcp_capabilities():
    """
    获取MCP能力清单
    
    返回AI可以执行的所有操作和管理的所有目标类型
    """
    return unified_mcp_service.get_capabilities()


@router.get("/audit/history")
async def get_operation_history(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    target_type: str = None,
    action: str = None,
    success_only: bool = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户MCP操作历史
    
    支持按目标类型、操作类型、成功状态筛选
    """
    try:
        history = mcp_audit_service.get_user_operation_history(
            db=db,
            user_id=current_user.id,
            limit=limit,
            target_type=target_type,
            action=action,
            success_only=success_only
        )
        
        return {
            "user_id": current_user.id,
            "total_records": len(history),
            "operations": [
                {
                    "id": log.id,
                    "target_type": log.target_type,
                    "action": log.action,
                    "novel_id": log.novel_id,
                    "target_id": log.target_id,
                    "success": log.success,
                    "execution_time_ms": log.execution_time_ms,
                    "ai_tokens_used": log.ai_tokens_used,
                    "created_at": log.created_at.isoformat(),
                    "error_message": log.error_message
                }
                for log in history
            ]
        }
        
    except Exception as e:
        logger.error(f"获取操作历史失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史失败: {str(e)}"
        )


@router.get("/audit/novel/{novel_id}/history")
async def get_novel_operation_history(
    novel_id: Annotated[int, Path(gt=0)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定小说的MCP操作历史
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        history = mcp_audit_service.get_novel_operation_history(
            db=db,
            user_id=current_user.id,
            novel_id=novel_id,
            limit=limit
        )
        
        return {
            "novel_id": novel_id,
            "novel_title": novel.title,
            "total_records": len(history),
            "operations": [
                {
                    "id": log.id,
                    "target_type": log.target_type,
                    "action": log.action,
                    "target_id": log.target_id,
                    "success": log.success,
                    "execution_time_ms": log.execution_time_ms,
                    "ai_tokens_used": log.ai_tokens_used,
                    "created_at": log.created_at.isoformat(),
                    "user_id": log.user_id,
                    "error_message": log.error_message
                }
                for log in history
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取小说操作历史失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史失败: {str(e)}"
        )


@router.get("/audit/statistics")
async def get_operation_statistics(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户MCP操作统计信息
    """
    try:
        stats = mcp_audit_service.get_operation_statistics(
            db=db,
            user_id=current_user.id,
            days=days
        )
        
        return {
            "user_id": current_user.id,
            "statistics": stats
        }
        
    except Exception as e:
        logger.error(f"获取操作统计失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取统计失败: {str(e)}"
        )


@router.get("/audit/novel/{novel_id}/statistics")
async def get_novel_operation_statistics(
    novel_id: Annotated[int, Path(gt=0)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取指定小说的MCP操作统计信息
    """
    try:
        # 验证小说权限
        novel = novel_crud.get_novel_by_id(db, novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="小说不存在或无权访问"
            )
        
        stats = mcp_audit_service.get_operation_statistics(
            db=db,
            user_id=current_user.id,
            novel_id=novel_id,
            days=days
        )
        
        return {
            "novel_id": novel_id,
            "novel_title": novel.title,
            "statistics": stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取小说操作统计失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取统计失败: {str(e)}"
        )


@router.get("/audit/errors")
async def get_error_analysis(
    days: Annotated[int, Query(ge=1, le=365)] = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取用户MCP操作错误分析
    """
    try:
        analysis = mcp_audit_service.get_error_analysis(
            db=db,
            user_id=current_user.id,
            days=days
        )
        
        return {
            "user_id": current_user.id,
            "error_analysis": analysis
        }
        
    except Exception as e:
        logger.error(f"获取错误分析失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取分析失败: {str(e)}"
        )


@router.get("/monitoring/performance")
async def get_performance_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取MCP系统性能指标
    """
    try:
        # 获取当前并发操作数
        owned_novel_ids = {
            novel_id
            for (novel_id,) in db.query(Novel.id).filter(
                Novel.user_id == current_user.id
            ).all()
        }
        concurrent_ops = {}
        for (operation_user_id, novel_id), count in unified_mcp_service._operation_counters.items():
            if (
                count > 0
                and operation_user_id == current_user.id
                and novel_id in owned_novel_ids
            ):
                concurrent_ops[novel_id] = count
        
        # 获取性能配置
        performance_config = unified_mcp_service.performance_config
        
        # 获取最近的性能统计
        recent_stats = mcp_audit_service.get_operation_statistics(
            db=db,
            user_id=current_user.id,
            days=1
        )
        
        return {
            "system_status": {
                "max_concurrent_operations": unified_mcp_service.max_concurrent_operations,
                "operation_timeout": unified_mcp_service.operation_timeout,
                "current_concurrent_operations": concurrent_ops,
                "total_active_operations": sum(concurrent_ops.values())
            },
            "performance_config": performance_config,
            "recent_performance": {
                "last_24h_operations": recent_stats["operation_summary"]["total_operations"],
                "last_24h_success_rate": recent_stats["operation_summary"]["success_rate"],
                "average_execution_time_ms": recent_stats["performance_metrics"]["average_execution_time_ms"]
            }
        }
        
    except Exception as e:
        logger.error(f"获取性能指标失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取指标失败: {str(e)}"
        )
