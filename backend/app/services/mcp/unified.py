"""统一 MCP 控制中心服务。

仅暴露已经连接真实业务链路的能力，未实现能力必须明确失败。
"""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder
from loguru import logger
from sqlalchemy.orm import Session

from app.crud.novel import get_novel_by_id
from app.models.worldview_schemas import (
    NovelAnalysisRequest,
    NovelAnalysisResponse,
    NovelOptimizationRequest,
    NovelOptimizationResponse,
    UnifiedMCPAction,
    UnifiedMCPResponse,
)
from app.services.mcp.character import character_mcp_service
from app.services.mcp.audit import mcp_audit_service


class UnifiedMCPService:
    """统一 MCP 控制中心。"""

    def __init__(self):
        # 只声明已经落到真实数据库或模型调用链的能力。未实现目标不能通过
        # “占位结果”伪装成成功。
        self.capability_matrix = {
            "character": {
                "create",
                "update",
                "delete",
                "analyze",
                "optimize",
                "get",
                "list",
                "search",
                "generate_character",
            }
        }
        self.target_handlers = {"character": self._handle_character}
        # 保留该属性供现有监控与测试读取，但内容来自真实能力矩阵。
        self.supported_actions = {
            action: self._handle_character
            for action in self.capability_matrix["character"]
        }

        self._operation_counters = {}
        self._counter_lock = asyncio.Lock()
        self.max_concurrent_operations = 5
        self.operation_timeout = 300

        self.performance_config = {
            "max_execution_time": 60,
            "warning_execution_time": 30,
            "max_ai_tokens": 50000,
            "warning_ai_tokens": 10000,
        }

    @asynccontextmanager
    async def _operation_context(
        self,
        user_id: int,
        novel_id: Optional[int],
        operation_id: str,
    ):
        """原子维护当前用户在指定小说上的操作计数，并限制执行时间。"""
        start_time = time.time()
        counter_key = (user_id, novel_id) if novel_id is not None else None
        counted = False

        # 用户与小说共同组成计数键，避免小说 ID 被复用时串租户。
        if counter_key is not None:
            async with self._counter_lock:
                current_ops = self._operation_counters.get(counter_key, 0)
                if current_ops >= self.max_concurrent_operations:
                    raise ValueError(
                        f"小说 {novel_id} 的并发操作数已达上限 "
                        f"({self.max_concurrent_operations})"
                    )
                self._operation_counters[counter_key] = current_ops + 1
                counted = True

        try:
            async with asyncio.timeout(self.operation_timeout):
                yield {
                    "start_time": start_time,
                    "operation_id": operation_id,
                }
        finally:
            if counted and counter_key is not None:
                async with self._counter_lock:
                    remaining = self._operation_counters.get(counter_key, 1) - 1
                    if remaining > 0:
                        self._operation_counters[counter_key] = remaining
                    else:
                        self._operation_counters.pop(counter_key, None)

            execution_time = time.time() - start_time
            if execution_time > self.performance_config["warning_execution_time"]:
                logger.warning(
                    f"MCP操作执行时间较长: {operation_id} "
                    f"耗时 {execution_time:.2f}秒"
                )

    async def execute_unified_action(
        self,
        db: Session,
        action: UnifiedMCPAction,
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> UnifiedMCPResponse:
        """鉴权后将统一 MCP 动作分派到真实处理器。"""
        operation_id = (
            f"{action.target_type}.{action.action}.{user_id}.{int(time.time())}"
        )
        start_time = time.time()

        try:
            # 所有权校验必须先于并发计数，避免越权请求占用其他用户的配额。
            if action.novel_id is None:
                response = UnifiedMCPResponse(
                    success=False,
                    target_type=action.target_type,
                    action=action.action,
                    message="必须提供小说ID",
                    timestamp=datetime.utcnow(),
                )
                await self._log_operation(
                    db,
                    action,
                    response,
                    user_id,
                    start_time,
                    ip_address,
                    user_agent,
                )
                return response

            novel = get_novel_by_id(db, action.novel_id)
            if not novel or novel.user_id != user_id:
                response = UnifiedMCPResponse(
                    success=False,
                    target_type=action.target_type,
                    action=action.action,
                    message="小说不存在或无权访问",
                    timestamp=datetime.utcnow(),
                )
                await self._log_operation(
                    db,
                    action,
                    response,
                    user_id,
                    start_time,
                    ip_address,
                    user_agent,
                )
                return response

            async with self._operation_context(
                user_id,
                action.novel_id,
                operation_id,
            ):
                if action.target_type not in self.capability_matrix:
                    response = UnifiedMCPResponse(
                        success=False,
                        target_type=action.target_type,
                        action=action.action,
                        message=f"目标类型尚未实现: {action.target_type}",
                        timestamp=datetime.utcnow(),
                    )
                    await self._log_operation(
                        db,
                        action,
                        response,
                        user_id,
                        start_time,
                        ip_address,
                        user_agent,
                    )
                    return response

                if action.action not in self.capability_matrix[action.target_type]:
                    response = UnifiedMCPResponse(
                        success=False,
                        target_type=action.target_type,
                        action=action.action,
                        message=f"操作尚未实现: {action.target_type}.{action.action}",
                        timestamp=datetime.utcnow(),
                    )
                    await self._log_operation(
                        db,
                        action,
                        response,
                        user_id,
                        start_time,
                        ip_address,
                        user_agent,
                    )
                    return response

                handler = self.target_handlers[action.target_type]
                result = await handler(db, action, user_id)
                response = UnifiedMCPResponse(
                    success=True,
                    target_type=action.target_type,
                    action=action.action,
                    target_id=result.get("target_id"),
                    result=result,
                    message=result.get(
                        "message",
                        f"操作 {action.action} 在 {action.target_type} 上执行成功",
                    ),
                    ai_reasoning=result.get("ai_reasoning"),
                    timestamp=datetime.utcnow(),
                )

                await self._log_operation(
                    db,
                    action,
                    response,
                    user_id,
                    start_time,
                    ip_address,
                    user_agent,
                )
                return response

        except asyncio.TimeoutError:
            logger.error(f"MCP操作超时: {operation_id}")
            response = UnifiedMCPResponse(
                success=False,
                target_type=action.target_type,
                action=action.action,
                message=f"操作超时 (>{self.operation_timeout}秒)",
                timestamp=datetime.utcnow(),
            )
            await self._log_operation(
                db,
                action,
                response,
                user_id,
                start_time,
                ip_address,
                user_agent,
            )
            return response
        except Exception as exc:  # noqa: BLE001
            logger.error(f"统一MCP操作失败: {operation_id} - {exc}")
            response = UnifiedMCPResponse(
                success=False,
                target_type=action.target_type,
                action=action.action,
                message=f"操作失败: {exc}",
                timestamp=datetime.utcnow(),
            )
            await self._log_operation(
                db,
                action,
                response,
                user_id,
                start_time,
                ip_address,
                user_agent,
            )
            return response

    def get_capabilities(self) -> Dict[str, Any]:
        """返回与真实处理器一致的能力清单。"""
        return {
            "target_types": {
                target: {
                    "actions": sorted(actions),
                    "implemented": True,
                }
                for target, actions in self.capability_matrix.items()
            },
            "action_types": sorted(
                {
                    action
                    for actions in self.capability_matrix.values()
                    for action in actions
                }
            ),
        }

    async def _log_operation(
        self,
        db: Session,
        action: UnifiedMCPAction,
        response: UnifiedMCPResponse,
        user_id: int,
        start_time: float,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """记录操作日志；审计失败不改变主要操作响应。"""
        try:
            execution_time_ms = int((time.time() - start_time) * 1000)
            await mcp_audit_service.log_mcp_operation(
                db=db,
                action=action,
                response=response,
                user_id=user_id,
                execution_time_ms=execution_time_ms,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"记录MCP操作日志失败: {exc}")

    async def analyze_novel_comprehensive(
        self,
        db: Session,
        request: NovelAnalysisRequest,
        user_id: int,
    ) -> NovelAnalysisResponse:
        """明确拒绝尚未接入真实数据链路的小说综合分析。"""
        raise NotImplementedError("小说综合分析尚未接入真实数据链路")

    async def optimize_novel_comprehensive(
        self,
        db: Session,
        request: NovelOptimizationRequest,
        user_id: int,
    ) -> NovelOptimizationResponse:
        """明确拒绝尚未接入真实数据链路的小说综合优化。"""
        raise NotImplementedError("小说综合优化尚未接入真实数据链路")

    async def _handle_character(
        self,
        db: Session,
        action: UnifiedMCPAction,
        user_id: int,
    ) -> Dict[str, Any]:
        """把已鉴权的统一动作转换为角色 MCP 动作。"""
        from app.models.character_schemas import MCPCharacterAction

        parameters = dict(action.parameters)
        parameters["novel_id"] = action.novel_id

        if action.target_id is not None:
            from app.crud.character import get_character

            character = get_character(db, action.target_id)
            if not character or character.novel_id != action.novel_id:
                raise ValueError("角色不存在或不属于该小说")

        character_action = MCPCharacterAction(
            action=action.action,
            character_id=action.target_id,
            novel_id=action.novel_id,
            parameters=parameters,
            context=action.context,
        )
        result = await character_mcp_service.execute_action(
            db,
            character_action,
            user_id,
        )
        if not result.success:
            raise ValueError(result.message)

        character_result = jsonable_encoder(dict(result.result or {}))
        # 角色生成内部可能携带完整世界观和请求上下文，统一响应只返回业务结果。
        character_result.pop("generation_context", None)

        return {
            "target_id": result.character_id,
            "character_result": character_result,
            "message": f"角色{action.action}操作完成",
            "ai_reasoning": "基于角色设定和关系网络进行角色管理",
        }


unified_mcp_service = UnifiedMCPService()
