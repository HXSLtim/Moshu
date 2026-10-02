"""
MCP操作审计服务
记录和跟踪所有MCP操作的执行情况
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.models.mcp_audit import MCPAuditLog
from app.models.novel import Novel
from app.models.worldview_schemas import UnifiedMCPAction, UnifiedMCPResponse
from loguru import logger


class MCPAuditService:
    """MCP审计服务"""
    
    def __init__(self):
        self.performance_thresholds = {
            "execution_time_warning": 30000,  # 30秒警告
            "execution_time_critical": 60000,  # 60秒严重
            "token_usage_warning": 10000,      # 10k token警告
            "token_usage_critical": 50000      # 50k token严重
        }
    
    async def log_mcp_operation(
        self,
        db: Session,
        action: UnifiedMCPAction,
        response: UnifiedMCPResponse,
        user_id: int,
        execution_time_ms: Optional[int] = None,
        ai_tokens_used: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> MCPAuditLog:
        """记录MCP操作日志"""
        try:
            audit_log = MCPAuditLog(
                user_id=user_id,
                novel_id=action.novel_id,
                target_type=action.target_type,
                action=action.action,
                target_id=action.target_id,
                parameters=jsonable_encoder(action.parameters),
                context=action.context,
                ai_instructions=action.ai_instructions,
                success=response.success,
                result_data=jsonable_encoder(response.result) if response.result is not None else None,
                error_message=response.message if not response.success else None,
                ai_reasoning=response.ai_reasoning,
                execution_time_ms=execution_time_ms,
                ai_tokens_used=ai_tokens_used,
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            db.add(audit_log)
            db.commit()
            db.refresh(audit_log)
            
            # 性能监控和告警
            await self._check_performance_metrics(audit_log)
            
            logger.info(
                f"MCP操作已记录: {action.target_type}.{action.action} "
                f"用户:{user_id} 结果:{'成功' if response.success else '失败'}"
            )
            
            return audit_log
            
        except Exception as e:
            logger.error(f"记录MCP审计日志失败: {str(e)}")
            # 审计日志记录失败不应该影响主要操作
            raise
    
    async def _check_performance_metrics(self, audit_log: MCPAuditLog):
        """检查性能指标并发出告警"""
        warnings = []
        
        # 检查执行时间
        if audit_log.execution_time_ms:
            if audit_log.execution_time_ms > self.performance_thresholds["execution_time_critical"]:
                warnings.append(f"执行时间严重超标: {audit_log.execution_time_ms}ms")
                logger.critical(
                    f"MCP操作执行时间严重超标: {audit_log.target_type}.{audit_log.action} "
                    f"耗时 {audit_log.execution_time_ms}ms"
                )
            elif audit_log.execution_time_ms > self.performance_thresholds["execution_time_warning"]:
                warnings.append(f"执行时间超标: {audit_log.execution_time_ms}ms")
                logger.warning(
                    f"MCP操作执行时间超标: {audit_log.target_type}.{audit_log.action} "
                    f"耗时 {audit_log.execution_time_ms}ms"
                )
        
        # 检查Token使用量
        if audit_log.ai_tokens_used:
            if audit_log.ai_tokens_used > self.performance_thresholds["token_usage_critical"]:
                warnings.append(f"Token使用量严重超标: {audit_log.ai_tokens_used}")
                logger.critical(
                    f"MCP操作Token使用严重超标: {audit_log.target_type}.{audit_log.action} "
                    f"使用 {audit_log.ai_tokens_used} tokens"
                )
            elif audit_log.ai_tokens_used > self.performance_thresholds["token_usage_warning"]:
                warnings.append(f"Token使用量超标: {audit_log.ai_tokens_used}")
                logger.warning(
                    f"MCP操作Token使用超标: {audit_log.target_type}.{audit_log.action} "
                    f"使用 {audit_log.ai_tokens_used} tokens"
                )
        
        return warnings

    @staticmethod
    def _scope_query_to_user_novels(query, user_id: int):
        """限制为当前用户自己的审计及其仍然拥有的小说。

        审计表不使用小说外键，以便保留失败操作记录。因此必须在读取时同时
        校验审计用户和小说当前所有权，避免 SQLite 删除后复用主键造成串租户。
        未绑定小说的当前用户审计仍然可见。
        """
        owned_novel_exists = exists().where(
            Novel.id == MCPAuditLog.novel_id,
            Novel.user_id == user_id,
        )
        return query.filter(
            MCPAuditLog.user_id == user_id,
            or_(
                MCPAuditLog.novel_id.is_(None),
                owned_novel_exists,
            ),
        )
    
    def get_user_operation_history(
        self,
        db: Session,
        user_id: int,
        limit: int = 50,
        target_type: Optional[str] = None,
        action: Optional[str] = None,
        success_only: Optional[bool] = None
    ) -> List[MCPAuditLog]:
        """获取用户操作历史"""
        query = self._scope_query_to_user_novels(
            db.query(MCPAuditLog),
            user_id,
        )
        
        if target_type:
            query = query.filter(MCPAuditLog.target_type == target_type)
        
        if action:
            query = query.filter(MCPAuditLog.action == action)
        
        if success_only is not None:
            query = query.filter(MCPAuditLog.success == success_only)
        
        return query.order_by(MCPAuditLog.created_at.desc()).limit(limit).all()
    
    def get_novel_operation_history(
        self,
        db: Session,
        user_id: int,
        novel_id: int,
        limit: int = 100
    ) -> List[MCPAuditLog]:
        """获取小说操作历史"""
        query = self._scope_query_to_user_novels(
            db.query(MCPAuditLog),
            user_id,
        )
        return query.filter(
            MCPAuditLog.novel_id == novel_id,
        ).order_by(MCPAuditLog.created_at.desc()).limit(limit).all()
    
    def get_operation_statistics(
        self,
        db: Session,
        user_id: int,
        novel_id: Optional[int] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """获取操作统计信息"""
        from datetime import timedelta
        
        # 计算时间范围
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query = self._scope_query_to_user_novels(
            db.query(MCPAuditLog),
            user_id,
        ).filter(MCPAuditLog.created_at >= start_date)

        if novel_id is not None:
            query = query.filter(MCPAuditLog.novel_id == novel_id)
        
        # 基础统计
        total_operations = query.count()
        successful_operations = query.filter(MCPAuditLog.success == True).count()
        failed_operations = total_operations - successful_operations
        
        # 按目标类型统计
        target_type_stats = self._scope_query_to_user_novels(
            db.query(
                MCPAuditLog.target_type,
                func.count(MCPAuditLog.id).label('count')
            ),
            user_id,
        ).filter(MCPAuditLog.created_at >= start_date)

        if novel_id is not None:
            target_type_stats = target_type_stats.filter(MCPAuditLog.novel_id == novel_id)
        
        target_type_stats = target_type_stats.group_by(MCPAuditLog.target_type).all()
        
        # 按操作类型统计
        action_stats = self._scope_query_to_user_novels(
            db.query(
                MCPAuditLog.action,
                func.count(MCPAuditLog.id).label('count')
            ),
            user_id,
        ).filter(MCPAuditLog.created_at >= start_date)

        if novel_id is not None:
            action_stats = action_stats.filter(MCPAuditLog.novel_id == novel_id)
        
        action_stats = action_stats.group_by(MCPAuditLog.action).all()
        
        # 性能统计
        avg_execution_time = self._scope_query_to_user_novels(
            db.query(func.avg(MCPAuditLog.execution_time_ms)),
            user_id,
        ).filter(
            and_(
                MCPAuditLog.created_at >= start_date,
                MCPAuditLog.execution_time_ms.isnot(None)
            )
        )

        if novel_id is not None:
            avg_execution_time = avg_execution_time.filter(MCPAuditLog.novel_id == novel_id)
        
        avg_execution_time = avg_execution_time.scalar()
        
        return {
            "time_range": {
                "start_date": start_date.isoformat(),
                "end_date": datetime.utcnow().isoformat(),
                "days": days
            },
            "operation_summary": {
                "total_operations": total_operations,
                "successful_operations": successful_operations,
                "failed_operations": failed_operations,
                "success_rate": successful_operations / total_operations if total_operations > 0 else 0
            },
            "target_type_distribution": {
                stat.target_type: stat.count for stat in target_type_stats
            },
            "action_distribution": {
                stat.action: stat.count for stat in action_stats
            },
            "performance_metrics": {
                "average_execution_time_ms": avg_execution_time,
                "average_execution_time_seconds": avg_execution_time / 1000 if avg_execution_time else None
            }
        }
    
    def get_error_analysis(
        self,
        db: Session,
        user_id: int,
        days: int = 7
    ) -> Dict[str, Any]:
        """获取错误分析"""
        from datetime import timedelta
        
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query = self._scope_query_to_user_novels(
            db.query(MCPAuditLog),
            user_id,
        ).filter(
            and_(
                MCPAuditLog.created_at >= start_date,
                MCPAuditLog.success == False
            )
        )
        
        # 错误统计
        error_logs = query.all()
        
        # 按错误类型分组
        error_patterns = {}
        for log in error_logs:
            if log.error_message:
                # 简化错误消息进行分组
                error_key = log.error_message[:50] + "..." if len(log.error_message) > 50 else log.error_message
                if error_key not in error_patterns:
                    error_patterns[error_key] = {
                        "count": 0,
                        "target_types": set(),
                        "actions": set(),
                        "first_occurrence": log.created_at,
                        "last_occurrence": log.created_at
                    }
                
                error_patterns[error_key]["count"] += 1
                error_patterns[error_key]["target_types"].add(log.target_type)
                error_patterns[error_key]["actions"].add(log.action)
                
                if log.created_at < error_patterns[error_key]["first_occurrence"]:
                    error_patterns[error_key]["first_occurrence"] = log.created_at
                if log.created_at > error_patterns[error_key]["last_occurrence"]:
                    error_patterns[error_key]["last_occurrence"] = log.created_at
        
        # 转换集合为列表以便JSON序列化
        for pattern in error_patterns.values():
            pattern["target_types"] = list(pattern["target_types"])
            pattern["actions"] = list(pattern["actions"])
            pattern["first_occurrence"] = pattern["first_occurrence"].isoformat()
            pattern["last_occurrence"] = pattern["last_occurrence"].isoformat()
        
        return {
            "analysis_period": {
                "start_date": start_date.isoformat(),
                "end_date": datetime.utcnow().isoformat(),
                "days": days
            },
            "total_errors": len(error_logs),
            "error_patterns": error_patterns,
            "recommendations": self._generate_error_recommendations(error_patterns)
        }
    
    def _generate_error_recommendations(self, error_patterns: Dict[str, Any]) -> List[str]:
        """生成错误处理建议"""
        recommendations = []
        
        # 分析高频错误
        high_frequency_errors = [
            (pattern, data) for pattern, data in error_patterns.items() 
            if data["count"] >= 5
        ]
        
        if high_frequency_errors:
            recommendations.append("发现高频错误，建议优先修复以下问题：")
            for pattern, data in high_frequency_errors:
                recommendations.append(f"- {pattern} (发生{data['count']}次)")
        
        # 分析错误趋势
        recent_errors = [
            (pattern, data) for pattern, data in error_patterns.items()
            if (datetime.utcnow() - datetime.fromisoformat(data["last_occurrence"])).days <= 1
        ]
        
        if recent_errors:
            recommendations.append("发现近期新增错误，建议及时关注：")
            for pattern, data in recent_errors:
                recommendations.append(f"- {pattern}")
        
        if not recommendations:
            recommendations.append("当前错误率较低，系统运行稳定")
        
        return recommendations


# 创建全局服务实例
mcp_audit_service = MCPAuditService()
