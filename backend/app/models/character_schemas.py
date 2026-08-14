"""
角色管理相关的Pydantic Schema
"""
import json
from typing import Annotated, List, Literal, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime


# ========== 角色基础Schema ==========

BoundedSkill = Annotated[str, Field(min_length=1, max_length=200)]
BoundedOptimizationText = Annotated[str, Field(min_length=1, max_length=500)]

class CharacterBase(BaseModel):
    """角色基础信息"""
    name: str = Field(..., min_length=1, max_length=100, description="角色姓名")
    age: Optional[int] = Field(None, ge=0, le=1000, description="角色年龄")
    gender: Optional[str] = Field(None, max_length=20, description="角色性别")
    occupation: Optional[str] = Field(None, max_length=100, description="角色职业")
    appearance: Optional[str] = Field(None, max_length=4_000, description="外貌描述")
    personality: Optional[str] = Field(None, max_length=4_000, description="性格特征")
    background: Optional[str] = Field(None, max_length=8_000, description="背景故事")
    skills: Optional[List[BoundedSkill]] = Field(
        default_factory=list,
        max_length=50,
        description="技能列表",
    )
    relationships: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        max_length=50,
        description="关系网络",
    )
    character_arc: Optional[str] = Field(None, max_length=8_000, description="角色弧线")
    importance_level: Literal["main", "secondary", "minor"] = Field(
        default="secondary",
        description="重要性级别",
    )
    first_appearance_chapter: Optional[int] = Field(None, gt=0, description="首次出现章节")

    @model_validator(mode="after")
    def validate_relationship_budget(self):
        """限制嵌套关系信息，防止角色卡在 AI 链路中无限放大。"""
        serialized = json.dumps(self.relationships or {}, ensure_ascii=False, default=str)
        if len(serialized) > 20_000:
            raise ValueError("角色关系数据不能超过 20000 个字符")
        return self


class CharacterCreate(CharacterBase):
    """创建角色请求"""
    novel_id: int = Field(..., gt=0, description="所属小说ID")


class CharacterUpdate(BaseModel):
    """更新角色请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=1000)
    gender: Optional[str] = Field(None, max_length=20)
    occupation: Optional[str] = Field(None, max_length=100)
    appearance: Optional[str] = Field(None, max_length=4_000)
    personality: Optional[str] = Field(None, max_length=4_000)
    background: Optional[str] = Field(None, max_length=8_000)
    skills: Optional[List[BoundedSkill]] = Field(None, max_length=50)
    relationships: Optional[Dict[str, Any]] = Field(None, max_length=50)
    character_arc: Optional[str] = Field(None, max_length=8_000)
    importance_level: Optional[Literal["main", "secondary", "minor"]] = None
    first_appearance_chapter: Optional[int] = Field(None, gt=0)
    last_appearance_chapter: Optional[int] = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_relationship_budget(self):
        """更新请求沿用角色关系总量预算。"""
        serialized = json.dumps(self.relationships or {}, ensure_ascii=False, default=str)
        if len(serialized) > 20_000:
            raise ValueError("角色关系数据不能超过 20000 个字符")
        return self


class CharacterResponse(BaseModel):
    """角色响应。

    读取模型不继承新写入约束，避免历史角色的枚举值、长文本或
    旧章节编号因新规则在响应序列化时变成 500。
    """
    id: int
    novel_id: int
    name: str
    age: Optional[int] = None
    gender: Optional[str] = None
    occupation: Optional[str] = None
    appearance: Optional[str] = None
    personality: Optional[str] = None
    background: Optional[str] = None
    skills: Optional[List[str]] = Field(default_factory=list)
    relationships: Optional[Dict[str, Any]] = Field(default_factory=dict)
    character_arc: Optional[str] = None
    importance_level: Optional[str] = "secondary"
    first_appearance_chapter: Optional[int] = None
    last_appearance_chapter: Optional[int] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== 角色关系Schema ==========

class CharacterRelationshipBase(BaseModel):
    """角色关系基础信息"""
    relationship_type: str = Field(..., max_length=50, description="关系类型")
    description: Optional[str] = Field(None, max_length=4_000, description="关系描述")
    strength: int = Field(default=5, ge=1, le=10, description="关系强度")
    development_stage: Optional[str] = Field(None, max_length=50, description="发展阶段")
    established_in_chapter: Optional[int] = Field(None, gt=0, description="建立关系的章节")


class CharacterRelationshipCreate(CharacterRelationshipBase):
    """创建角色关系请求"""
    novel_id: int = Field(..., gt=0, description="所属小说ID")
    character_a_id: int = Field(..., gt=0, description="角色A的ID")
    character_b_id: int = Field(..., gt=0, description="角色B的ID")


class CharacterRelationshipUpdate(BaseModel):
    """更新角色关系请求"""
    relationship_type: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=4_000)
    strength: Optional[int] = Field(None, ge=1, le=10)
    development_stage: Optional[str] = Field(None, max_length=50)


class CharacterRelationshipResponse(BaseModel):
    """角色关系响应，兼容早期未受写入预算约束的数据。"""
    id: int
    novel_id: int
    character_a_id: int
    character_b_id: int
    relationship_type: str
    description: Optional[str] = None
    strength: int = 5
    development_stage: Optional[str] = None
    established_in_chapter: Optional[int] = None
    character_a_name: str
    character_b_name: str
    change_history: Optional[List[Dict[str, Any]]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== 角色出场记录Schema ==========

class CharacterAppearanceBase(BaseModel):
    """角色出场基础信息"""
    appearance_type: Literal["main", "supporting", "mentioned"] = Field(
        default="supporting",
        description="出场类型",
    )
    description: Optional[str] = Field(None, max_length=4_000, description="出场描述")
    importance_in_chapter: int = Field(default=5, ge=1, le=10, description="在章节中的重要性")
    status_changes: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        max_length=50,
        description="状态变化",
    )

    @model_validator(mode="after")
    def validate_status_change_budget(self):
        """条目数与 JSON 总量同时受限，防止单个嵌套值无界膨胀。"""
        serialized = json.dumps(self.status_changes or {}, ensure_ascii=False, default=str)
        if len(serialized) > 20_000:
            raise ValueError("角色状态变化不能超过 20000 个字符")
        return self


class CharacterAppearanceCreate(CharacterAppearanceBase):
    """创建角色出场记录请求"""
    character_id: int = Field(..., gt=0, description="角色ID")
    chapter_id: int = Field(..., gt=0, description="章节ID")


class CharacterAppearanceResponse(BaseModel):
    """角色出场记录响应，不用新写入枚举限制拒绝历史值。"""
    id: int
    character_id: int
    chapter_id: int
    appearance_type: str = "supporting"
    description: Optional[str] = None
    importance_in_chapter: int = 5
    status_changes: Optional[Dict[str, Any]] = Field(default_factory=dict)
    character_name: str
    chapter_number: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ========== AI分析相关Schema ==========

class CharacterAnalysisRequest(BaseModel):
    """角色分析请求"""
    model_config = ConfigDict(extra="forbid")

    character_id: int = Field(..., gt=0, description="角色ID")
    analysis_type: str = Field(default="comprehensive", min_length=1, max_length=50, description="分析类型")
    include_relationships: bool = Field(default=True, description="是否包含关系分析")
    include_development: bool = Field(default=True, description="是否包含发展分析")


class CharacterAnalysisResponse(BaseModel):
    """角色分析响应"""
    character_id: int
    character_name: str
    analysis_type: str
    
    # 分析结果
    personality_analysis: Optional[Dict[str, Any]] = None
    development_analysis: Optional[Dict[str, Any]] = None
    relationship_analysis: Optional[Dict[str, Any]] = None
    consistency_check: Optional[Dict[str, Any]] = None
    improvement_suggestions: Optional[List[str]] = None
    
    # 元数据
    analysis_timestamp: datetime
    confidence_score: Optional[float] = None


class CharacterOptimizationRequest(BaseModel):
    """角色优化请求"""
    model_config = ConfigDict(extra="forbid")

    character_id: int = Field(..., gt=0, description="角色ID")
    optimization_goals: List[BoundedOptimizationText] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="优化目标",
    )
    preserve_traits: Optional[List[BoundedOptimizationText]] = Field(
        default_factory=list,
        max_length=50,
        description="保持的特征",
    )


class CharacterOptimizationResponse(BaseModel):
    """角色优化响应"""
    character_id: int
    original_character: CharacterResponse
    optimized_suggestions: Dict[str, Any]
    reasoning: str
    confidence_score: float


# ========== MCP相关Schema ==========

class MCPCharacterAction(BaseModel):
    """MCP角色操作"""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="操作类型: create, update, delete, analyze, optimize",
    )
    character_id: Optional[int] = Field(None, gt=0, description="角色ID")
    novel_id: Optional[int] = Field(None, gt=0, description="小说ID")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        max_length=50,
        description="操作参数",
    )
    context: Optional[str] = Field(None, max_length=4_000, description="操作上下文")

    @model_validator(mode="after")
    def validate_parameter_budget(self):
        """限制嵌套参数总量，避免 MCP 调用制造无界模型上下文。"""
        serialized = json.dumps(self.parameters, ensure_ascii=False, default=str)
        if len(serialized) > 20_000:
            raise ValueError("角色 MCP 参数不能超过 20000 个字符")
        return self


class MCPCharacterResponse(BaseModel):
    """MCP角色操作响应"""
    success: bool
    action: str
    character_id: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    message: str
    timestamp: datetime


class CharacterNetworkResponse(BaseModel):
    """角色关系网络响应"""
    novel_id: int
    characters: List[CharacterResponse]
    relationships: List[CharacterRelationshipResponse]
    network_analysis: Optional[Dict[str, Any]] = None


class CharacterTimelineResponse(BaseModel):
    """角色时间线响应"""
    character_id: int
    character_name: str
    appearances: List[CharacterAppearanceResponse]
    development_milestones: Optional[List[Dict[str, Any]]] = None
    relationship_changes: Optional[List[Dict[str, Any]]] = None
