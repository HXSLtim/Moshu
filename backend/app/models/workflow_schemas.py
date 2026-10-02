"""
Agent工作流可视化相关Schema
用于前端展示AI和知识图谱等后台组件的工作流程和数据流
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    """单个工作流步骤信息

    用于描述某一步里由哪个Agent/组件执行了什么操作、使用了哪些数据源、产生了什么结果，
    方便前端进行可视化展示（时间线 / DAG / 数据流图）。
    """

    id: str = Field(..., description="步骤ID，需在一次工作流内唯一")
    parent_id: Optional[str] = Field(
        None, description="父步骤ID，用于构建依赖关系/有向图"
    )
    type: str = Field(
        ...,
        description=(
            "步骤类型，例如：agent/rag/graph/llm/consistency/db/index 等，"
            "用于前端选择不同的图标和样式"
        ),
    )
    agent_name: Optional[str] = Field(
        None,
        description="执行该步骤的Agent或组件名称，例如 WorldviewAgent/ConsistencyService",
    )
    title: str = Field(..., description="步骤的简短标题，用于列表或时间线展示")
    description: Optional[str] = Field(
        None, description="对该步骤做了什么的详细说明"
    )

    input: Dict[str, Any] = Field(
        default_factory=dict, description="该步骤的主要输入参数（经过脱敏和裁剪后的概要）"
    )
    output: Dict[str, Any] = Field(
        default_factory=dict, description="该步骤的主要输出结果概要"
    )

    data_sources: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "该步骤使用到的数据源，例如：RAG检索片段、知识图谱节点、时间线事件等，"
            "结构上推荐按类别拆分：{'rag_chunks': [...], 'graph_nodes': [...]}"
        ),
    )

    llm: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "如果该步骤调用了LLM，这里记录模型名称、温度、prompt模板摘要等信息，"
            "方便前端展示是哪个模型干的这一步。"
        ),
    )

    status: str = Field(
        default="completed",
        description="步骤状态：pending/running/completed/failed/skipped 等",
    )
    started_at: Optional[datetime] = Field(None, description="步骤开始时间（UTC）")
    finished_at: Optional[datetime] = Field(None, description="步骤结束时间（UTC）")
    duration_ms: Optional[int] = Field(
        None, description="执行耗时（毫秒），前端可用于展示性能/瓶颈"
    )


class WorkflowTrace(BaseModel):
    """一次完整工作流运行的追踪信息

    用于描述某次MCP操作/一致性检查/生成调用中，Agent和后端组件的整体协作流程。
    前端可以基于该结构绘制：
    - 时间线视图（按started_at排序）
    - DAG数据流图（根据id/parent_id构建）
    - 性能分析（根据duration_ms聚合）
    """

    run_id: str = Field(..., description="本次工作流运行ID，由后端生成并在整个调用链中传递")
    trigger: str = Field(
        ...,
        description=(
            "触发来源，例如：'mcp.analyze_novel' / 'mcp.optimize_novel' / "
            "'consistency.check_content' 等"
        ),
    )

    novel_id: Optional[int] = Field(None, description="关联的小说ID")
    chapter_id: Optional[int] = Field(None, description="关联的章节ID（如有）")
    user_id: Optional[int] = Field(None, description="触发该工作流的用户ID（如可用）")

    summary: Optional[str] = Field(
        None, description="本次工作流的简要说明，便于前端列表展示"
    )

    steps: List[WorkflowStep] = Field(
        default_factory=list, description="按执行顺序或依赖关系排列的步骤列表"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="工作流追踪创建时间"
    )

    class Config:
        """配置选项"""

        # 允许ORM对象转换为该Schema，方便后续如需持久化
        from_attributes = True
