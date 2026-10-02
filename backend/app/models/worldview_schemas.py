"""
世界观管理相关的Pydantic Schema
"""
import json
from typing import Annotated, List, Optional, Dict, Any, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime

from app.models.workflow_schemas import WorkflowTrace


BoundedAnalysisScope = Annotated[str, Field(min_length=1, max_length=50)]
BoundedOptimizationGoal = Annotated[str, Field(min_length=1, max_length=500)]


# ========== 世界观设定Schema ==========

class WorldviewSettingBase(BaseModel):
    """世界观设定基础信息"""
    category: str = Field(..., max_length=50, description="设定分类")
    name: str = Field(..., max_length=200, description="设定名称")
    description: str = Field(..., description="设定描述")
    details: Optional[Dict[str, Any]] = Field(default_factory=dict, description="详细设定数据")
    importance_level: str = Field(default="medium", description="重要性级别")
    consistency_rules: Optional[List[str]] = Field(default_factory=list, description="一致性规则")
    related_characters: Optional[List[int]] = Field(default_factory=list, description="相关角色ID")
    related_chapters: Optional[List[int]] = Field(default_factory=list, description="相关章节ID")


class WorldviewSettingCreate(WorldviewSettingBase):
    """创建世界观设定请求"""
    novel_id: int = Field(..., description="所属小说ID")


class WorldviewSettingUpdate(BaseModel):
    """更新世界观设定请求"""
    category: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    importance_level: Optional[str] = None
    consistency_rules: Optional[List[str]] = None
    related_characters: Optional[List[int]] = None
    related_chapters: Optional[List[int]] = None
    is_active: Optional[bool] = None


class WorldviewSettingResponse(WorldviewSettingBase):
    """世界观设定响应"""
    id: int
    novel_id: int
    ai_analysis: Optional[Dict[str, Any]] = None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== 情节元素Schema ==========

class PlotElementBase(BaseModel):
    """情节元素基础信息"""
    element_type: str = Field(..., max_length=50, description="情节类型")
    title: str = Field(..., max_length=200, description="情节标题")
    description: str = Field(..., description="情节描述")
    chapter_start: Optional[int] = Field(None, description="开始章节")
    chapter_end: Optional[int] = Field(None, description="结束章节")
    position_in_story: Optional[str] = Field(None, description="在故事中的位置")
    importance_score: int = Field(default=5, ge=1, le=10, description="重要性评分")
    emotional_impact: Optional[str] = Field(None, description="情感影响")
    plot_function: Optional[str] = Field(None, description="情节功能")
    involved_characters: Optional[List[int]] = Field(default_factory=list, description="涉及角色")
    affected_settings: Optional[List[int]] = Field(default_factory=list, description="影响设定")
    prerequisites: Optional[List[str]] = Field(default_factory=list, description="前置条件")
    consequences: Optional[List[str]] = Field(default_factory=list, description="后果影响")
    development_stage: str = Field(default="planned", description="发展阶段")


class PlotElementCreate(PlotElementBase):
    """创建情节元素请求"""
    novel_id: int = Field(..., description="所属小说ID")


class PlotElementUpdate(BaseModel):
    """更新情节元素请求"""
    element_type: Optional[str] = Field(None, max_length=50)
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    chapter_start: Optional[int] = None
    chapter_end: Optional[int] = None
    position_in_story: Optional[str] = None
    importance_score: Optional[int] = Field(None, ge=1, le=10)
    emotional_impact: Optional[str] = None
    plot_function: Optional[str] = None
    involved_characters: Optional[List[int]] = None
    affected_settings: Optional[List[int]] = None
    prerequisites: Optional[List[str]] = None
    consequences: Optional[List[str]] = None
    development_stage: Optional[str] = None


class PlotElementResponse(PlotElementBase):
    """情节元素响应"""
    id: int
    novel_id: int
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== 故事时间线Schema ==========

class StoryTimelineBase(BaseModel):
    """故事时间线基础信息"""
    timeline_point: str = Field(..., max_length=200, description="时间点")
    description: str = Field(..., description="描述")
    story_day: int = Field(default=1, description="故事内时间")
    real_time_reference: Optional[str] = Field(None, description="现实时间参考")
    duration: Optional[str] = Field(None, description="持续时间")
    involved_chapters: Optional[List[int]] = Field(default_factory=list, description="涉及章节")
    involved_characters: Optional[List[int]] = Field(default_factory=list, description="涉及角色")
    key_events: Optional[List[str]] = Field(default_factory=list, description="关键事件")
    timeline_type: str = Field(default="main", description="时间线类型")


class StoryTimelineCreate(StoryTimelineBase):
    """创建故事时间线请求"""
    novel_id: int = Field(..., description="所属小说ID")


class StoryTimelineUpdate(BaseModel):
    """更新故事时间线请求"""
    timeline_point: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    story_day: Optional[int] = None
    real_time_reference: Optional[str] = None
    duration: Optional[str] = None
    involved_chapters: Optional[List[int]] = None
    involved_characters: Optional[List[int]] = None
    key_events: Optional[List[str]] = None
    timeline_type: Optional[str] = None


class StoryTimelineResponse(StoryTimelineBase):
    """故事时间线响应"""
    id: int
    novel_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== 小说大纲Schema ==========

class NovelOutlineBase(BaseModel):
    """小说大纲基础信息"""
    level: int = Field(..., ge=1, le=5, description="大纲层级")
    parent_id: Optional[int] = Field(None, description="父级大纲ID")
    title: str = Field(..., max_length=200, description="大纲标题")
    summary: str = Field(..., description="大纲摘要")
    detailed_description: Optional[str] = Field(None, description="详细描述")
    order_index: int = Field(..., description="排序索引")
    estimated_word_count: int = Field(default=0, description="预估字数")
    completion_status: str = Field(default="planned", description="完成状态")
    related_characters: Optional[List[int]] = Field(default_factory=list, description="相关角色")
    key_plot_points: Optional[List[str]] = Field(default_factory=list, description="关键情节点")


class NovelOutlineCreate(NovelOutlineBase):
    """创建小说大纲请求"""
    novel_id: int = Field(..., description="所属小说ID")


class NovelOutlineUpdate(BaseModel):
    """更新小说大纲请求"""
    title: Optional[str] = Field(None, max_length=200)
    summary: Optional[str] = None
    detailed_description: Optional[str] = None
    order_index: Optional[int] = None
    estimated_word_count: Optional[int] = None
    completion_status: Optional[str] = None
    related_characters: Optional[List[int]] = None
    key_plot_points: Optional[List[str]] = None


class NovelOutlineResponse(NovelOutlineBase):
    """小说大纲响应"""
    id: int
    novel_id: int
    actual_word_count: int
    ai_generated: bool
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    children: Optional[List['NovelOutlineResponse']] = None

    class Config:
        from_attributes = True


# ========== 文风指南Schema ==========

class StyleGuideBase(BaseModel):
    """文风指南基础信息"""
    style_category: str = Field(..., max_length=50, description="文风分类")
    rules: Dict[str, Any] = Field(..., description="文风规则")
    examples: Optional[List[str]] = Field(default_factory=list, description="示例文本")
    tone: Optional[str] = Field(None, description="语调")
    pace: Optional[str] = Field(None, description="节奏")
    perspective: Optional[str] = Field(None, description="视角")
    applicable_scenes: Optional[List[str]] = Field(default_factory=list, description="适用场景")
    character_specific: Optional[Dict[str, Any]] = Field(default_factory=dict, description="角色特定文风")


class StyleGuideCreate(StyleGuideBase):
    """创建文风指南请求"""
    novel_id: int = Field(..., description="所属小说ID")


class StyleGuideUpdate(BaseModel):
    """更新文风指南请求"""
    style_category: Optional[str] = Field(None, max_length=50)
    rules: Optional[Dict[str, Any]] = None
    examples: Optional[List[str]] = None
    tone: Optional[str] = None
    pace: Optional[str] = None
    perspective: Optional[str] = None
    applicable_scenes: Optional[List[str]] = None
    character_specific: Optional[Dict[str, Any]] = None


class StyleGuideResponse(StyleGuideBase):
    """文风指南响应"""
    id: int
    novel_id: int
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ========== MCP统一操作Schema ==========

class UnifiedMCPAction(BaseModel):
    """统一MCP操作"""

    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="目标类型: worldview, plot, timeline, outline, style, character",
    )
    action: str = Field(..., min_length=1, max_length=50, description="操作类型")
    target_id: Optional[int] = Field(None, gt=0, description="目标ID")
    novel_id: Optional[int] = Field(None, gt=0, description="小说ID")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        max_length=50,
        description="操作参数",
    )
    context: Optional[str] = Field(None, max_length=4_000, description="操作上下文")
    ai_instructions: Optional[str] = Field(None, max_length=2_000, description="AI指令")

    @model_validator(mode="after")
    def validate_parameter_budget(self):
        """限制嵌套参数的序列化体积，避免字典层级绕过字段长度预算。"""
        serialized = json.dumps(self.parameters, ensure_ascii=False, default=str)
        if len(serialized) > 20_000:
            raise ValueError("MCP 操作参数不能超过 20000 个字符")
        return self


class UnifiedMCPResponse(BaseModel):
    """统一MCP操作响应"""
    success: bool
    target_type: str
    action: str
    target_id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    message: str
    ai_reasoning: Optional[str] = None
    timestamp: datetime
    workflow_trace: Optional[WorkflowTrace] = Field(
        default=None,
        description="本次MCP操作的Agent工作流追踪信息，供前端可视化展示",
    )


class NovelAnalysisRequest(BaseModel):
    """小说分析请求"""
    model_config = ConfigDict(extra="forbid")

    novel_id: int = Field(..., gt=0, description="小说ID")
    analysis_scope: List[BoundedAnalysisScope] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="分析范围",
    )
    analysis_depth: str = Field(default="comprehensive", min_length=1, max_length=50, description="分析深度")
    include_suggestions: bool = Field(default=True, description="是否包含建议")


class NovelAnalysisResponse(BaseModel):
    """小说分析响应"""
    novel_id: int
    analysis_scope: List[str]
    
    # 分析结果
    worldview_analysis: Optional[Dict[str, Any]] = None
    character_analysis: Optional[Dict[str, Any]] = None
    plot_analysis: Optional[Dict[str, Any]] = None
    style_analysis: Optional[Dict[str, Any]] = None
    consistency_analysis: Optional[Dict[str, Any]] = None
    
    # 综合评估
    overall_score: Optional[float] = None
    strengths: Optional[List[str]] = None
    weaknesses: Optional[List[str]] = None
    improvement_suggestions: Optional[List[str]] = None
    
    # 元数据
    analysis_timestamp: datetime
    confidence_score: Optional[float] = None
    workflow_trace: Optional[WorkflowTrace] = Field(
        default=None,
        description="本次小说分析过程的Agent工作流追踪信息",
    )


class NovelOptimizationRequest(BaseModel):
    """小说优化请求"""
    model_config = ConfigDict(extra="forbid")

    novel_id: int = Field(..., gt=0, description="小说ID")
    optimization_goals: List[BoundedOptimizationGoal] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="优化目标",
    )
    target_areas: List[BoundedAnalysisScope] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="目标区域",
    )
    preserve_elements: Optional[List[BoundedOptimizationGoal]] = Field(
        default_factory=list,
        max_length=50,
        description="保持元素",
    )
    optimization_intensity: str = Field(default="moderate", min_length=1, max_length=50, description="优化强度")


class NovelOptimizationResponse(BaseModel):
    """小说优化响应"""
    novel_id: int
    optimization_goals: List[str]
    
    # 优化建议
    worldview_optimizations: Optional[Dict[str, Any]] = None
    character_optimizations: Optional[Dict[str, Any]] = None
    plot_optimizations: Optional[Dict[str, Any]] = None
    style_optimizations: Optional[Dict[str, Any]] = None
    
    # 实施计划
    implementation_plan: Optional[List[Dict[str, Any]]] = None
    priority_order: Optional[List[str]] = None
    estimated_impact: Optional[Dict[str, float]] = None
    
    # 元数据
    optimization_timestamp: datetime
    confidence_score: Optional[float] = None
    workflow_trace: Optional[WorkflowTrace] = Field(
        default=None,
        description="本次小说优化过程的Agent工作流追踪信息",
    )
