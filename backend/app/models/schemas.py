"""
Pydantic数据模型
定义API请求和响应的数据结构
"""
import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.workflow_schemas import WorkflowTrace


# 持久化请求保留比单次模型上下文更宽的容量，但不允许无界输入。
MAX_STYLE_SAMPLE_CHARS = 100_000
MAX_NOVEL_DESCRIPTION_CHARS = 8_000
MAX_NOVEL_WORLDVIEW_CHARS = 50_000
MAX_CHAPTER_CONTENT_CHARS = 500_000
MAX_PLOT_OPTIONS_CONTENT_CHARS = 50_000
MAX_REWRITE_SOURCE_CHARS = 20_000
MAX_RESEARCH_QUERY_CHARS = 500
MAX_NESTED_REQUEST_CHARS = 50_000

BoundedOutlineText = Annotated[str, Field(min_length=1, max_length=2_000)]


class StrictWriteModel(BaseModel):
    """写请求基类：拒绝未声明字段，避免客户端误以为更新已生效。"""

    model_config = ConfigDict(extra="forbid")


# ========== 用户认证相关模型 ==========

class UserBase(BaseModel):
    """用户基础Schema"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱地址")


class UserCreate(UserBase):
    """用户注册Schema"""
    password: str = Field(..., min_length=6, max_length=50, description="密码")


class UserLogin(StrictWriteModel):
    """用户登录Schema"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")


class UserResponse(UserBase):
    """用户响应Schema"""
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class StyleSampleCreate(StrictWriteModel):
    """文风样本创建请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    name: str = Field(..., min_length=1, max_length=100, description="文风名称")
    sample_text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_STYLE_SAMPLE_CHARS,
        description="文风样本文本",
    )


class StyleSampleResponse(BaseModel):
    """文风样本响应"""
    id: int
    novel_id: int
    name: str
    sample_preview: str
    style_features: List[str] = Field(default_factory=list)
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token响应Schema"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ========== 枚举类型 ==========

class StageType(str, Enum):
    """Agent类型枚举"""
    WORLDVIEW = "worldview"  # 世界观Agent
    CHARACTER = "character"  # 角色Agent
    PLOT = "plot"  # 剧情Agent


class ConsistencyCheckType(str, Enum):
    """一致性检查类型枚举"""
    RULE_ENGINE = "rule_engine"  # 规则引擎
    KNOWLEDGE_GRAPH = "knowledge_graph"  # 知识图谱
    TIMELINE = "timeline"  # 时间线
    EMOTION = "emotion"  # 情绪状态机


# ========== 小说相关模型 ==========


class NovelCreate(StrictWriteModel):
    """创建小说请求"""
    title: str = Field(..., min_length=1, max_length=200, description="小说标题")
    genre: Optional[str] = Field(None, max_length=50, description="小说类型（如玄幻、科幻等）")
    description: Optional[str] = Field(
        None,
        max_length=MAX_NOVEL_DESCRIPTION_CHARS,
        description="小说简介",
    )
    worldview: Optional[str] = Field(
        None,
        max_length=MAX_NOVEL_WORLDVIEW_CHARS,
        description="世界观设定",
    )


class NovelUpdate(StrictWriteModel):
    """更新小说请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="小说标题")
    genre: Optional[str] = Field(None, max_length=50, description="小说类型")
    description: Optional[str] = Field(
        None,
        max_length=MAX_NOVEL_DESCRIPTION_CHARS,
        description="小说简介",
    )
    worldview: Optional[str] = Field(
        None,
        max_length=MAX_NOVEL_WORLDVIEW_CHARS,
        description="世界观设定",
    )

    @model_validator(mode="after")
    def validate_update_fields(self):
        """拒绝空更新，同时允许显式传 null 清空可选字段。"""
        if not self.model_fields_set:
            raise ValueError("至少需要提供一个要更新的小说字段")
        return self


class NovelResponse(BaseModel):
    """小说响应"""
    rag_lifecycle_id: str
    id: int
    title: str
    genre: Optional[str]
    description: Optional[str]
    worldview: Optional[str]
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class NovelStatisticsItem(BaseModel):
    """单部小说的章节与字数统计。"""

    novel_id: int
    chapter_count: int
    total_words: int


class NovelStatisticsResponse(BaseModel):
    """当前用户全部小说的聚合统计。"""

    items: List[NovelStatisticsItem]


# ========== 章节相关模型 ==========

class ChapterCreate(StrictWriteModel):
    """创建章节请求"""
    chapter_number: int = Field(..., gt=0, description="章节号")
    title: str = Field(..., min_length=1, max_length=200, description="章节标题")
    # 新建章节时允许正文为空，用户可以稍后再填写
    content: str = Field(
        "",
        max_length=MAX_CHAPTER_CONTENT_CHARS,
        description="章节内容",
    )


class ChapterNextCreate(StrictWriteModel):
    """由服务端分配章节号的创建请求。"""

    title: Optional[str] = Field(None, min_length=1, max_length=200, description="章节标题")
    content: str = Field(
        "",
        max_length=MAX_CHAPTER_CONTENT_CHARS,
        description="章节内容",
    )

    @field_validator("title", mode="before")
    @classmethod
    def blank_title_uses_default(cls, value):
        """允许空标题：服务端会按章节号生成默认标题。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ChapterUpdate(StrictWriteModel):
    """更新章节请求"""
    expected_version: int = Field(..., ge=1, description="客户端读取到的章节版本")
    expected_novel_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    expected_chapter_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    chapter_number: Optional[int] = Field(None, gt=0, description="新的章节号")
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="章节标题")
    content: Optional[str] = Field(
        None,
        max_length=MAX_CHAPTER_CONTENT_CHARS,
        description="章节内容",
    )

    @model_validator(mode="after")
    def validate_update_fields(self):
        """更新请求必须至少修改一个业务字段。"""
        if self.chapter_number is None and self.title is None and self.content is None:
            raise ValueError("至少需要提供一个要更新的章节字段")
        return self


class ChapterResponse(BaseModel):
    """章节响应"""
    rag_lifecycle_id: str
    id: int
    novel_id: int
    chapter_number: int
    title: str
    content: str
    word_count: int
    version: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class ChapterSummary(BaseModel):
    """章节列表摘要，不携带正文。"""
    rag_lifecycle_id: str

    id: int
    novel_id: int
    chapter_number: int
    title: str
    word_count: int
    version: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ChapterPageResponse(BaseModel):
    """章节摘要分页响应。"""

    items: List[ChapterSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class EditorIssue(BaseModel):
    """网文编辑问题项（轻量审核用）"""
    type: str = Field(..., description="问题类型，如节奏/爽点/信息量/重复度/人物等")
    level: str = Field("info", description="严重程度：info/warn")
    message: str = Field(..., description="问题描述")
    suggestion: Optional[str] = Field(None, description="一句话修改建议")


class EditorReview(BaseModel):
    """网文编辑Agent整体审核结果"""
    score: int = Field(0, ge=0, le=100, description="整体评分（0-100，仅作参考）")
    summary: str = Field(..., description="编辑总体评价")
    issues: List[EditorIssue] = Field(default_factory=list, description="问题列表")
    suggested_tags: List[str] = Field(default_factory=list, description="建议标签，如爽文/慢热等")
    created_at: datetime


class ConsistencySummary(BaseModel):
    """一致性检查摘要"""
    has_conflict: bool = Field(..., description="是否存在一致性冲突")
    violations: List[str] = Field(default_factory=list, description="违规说明列表")
    checks_performed: List[str] = Field(default_factory=list, description="执行过的检查类型")


class ChapterWithReviewResponse(ChapterResponse):
    """带有编辑审核结果的章节响应，用于手动保存后返回"""
    editor_review: Optional[EditorReview] = Field(
        None,
        description="网文编辑Agent的轻量审核结果，为空表示本次未生成或解析失败",
    )
    consistency_summary: Optional[ConsistencySummary] = Field(
        None,
        description="章节内容一致性检查摘要（规则引擎、知识图谱、时间线等）",
    )


# ========== 世界观相关模型 ==========

class WorldviewRule(StrictWriteModel):
    """世界观规则"""
    name: str = Field(..., min_length=1, max_length=200, description="规则名称（如魔法等级上限）")
    value: Any = Field(..., description="规则值（如9）")
    description: Optional[str] = Field(None, max_length=4_000, description="规则说明")


class WorldviewCreate(StrictWriteModel):
    """创建世界观请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    name: str = Field(..., min_length=1, max_length=200, description="世界观名称（如魔法体系）")
    content: str = Field(..., min_length=1, max_length=MAX_NOVEL_WORLDVIEW_CHARS, description="世界观内容描述")
    rules: List[WorldviewRule] = Field(default_factory=list, max_length=100, description="硬规则列表")

    @model_validator(mode="after")
    def validate_rule_budget(self):
        """限制规则中 Any 嵌套值的总体积。"""
        serialized = json.dumps(
            [rule.model_dump(mode="json") for rule in self.rules],
            ensure_ascii=False,
            default=str,
        )
        if len(serialized) > MAX_NESTED_REQUEST_CHARS:
            raise ValueError("世界观规则不能超过 50000 个字符")
        return self


class WorldviewResponse(BaseModel):
    """世界观响应"""
    id: int
    novel_id: int
    name: str
    content: str
    rules: List["WorldviewRuleResponse"]
    created_at: datetime


class WorldviewRuleResponse(BaseModel):
    """世界观规则读取模型，不用新写入预算拒绝历史数据。"""

    name: str
    value: Any
    description: Optional[str] = None


# ========== 角色相关模型 ==========

class CharacterRelationship(StrictWriteModel):
    """角色关系"""
    target_character_id: int = Field(..., gt=0, description="目标角色ID")
    relationship_type: str = Field(..., min_length=1, max_length=50, description="关系类型（如朋友、敌人）")


class CharacterCreate(StrictWriteModel):
    """创建角色请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    name: str = Field(..., min_length=1, max_length=100, description="角色名称")
    personality: str = Field(..., min_length=1, max_length=4_000, description="性格描述")
    appearance: Optional[str] = Field(None, max_length=4_000, description="外貌描述")
    background: Optional[str] = Field(None, max_length=8_000, description="背景故事")
    relationships: List[CharacterRelationship] = Field(default_factory=list, max_length=50, description="角色关系")


class CharacterResponse(BaseModel):
    """角色响应"""
    id: int
    novel_id: int
    name: str
    personality: str
    appearance: Optional[str]
    background: Optional[str]
    relationships: List["CharacterRelationshipResponse"]
    current_emotion: str = "平静"
    created_at: datetime


class CharacterRelationshipResponse(BaseModel):
    """历史角色关系读取模型。"""

    target_character_id: int
    relationship_type: str


# ========== 大纲相关模型 ==========

class OutlineNode(StrictWriteModel):
    """大纲节点"""
    chapter: int = Field(..., gt=0, description="章节号")
    title: str = Field(..., min_length=1, max_length=200, description="章节标题")
    plot_points: List[BoundedOutlineText] = Field(..., min_length=1, max_length=50, description="剧情点列表")
    foreshadowing: List[BoundedOutlineText] = Field(default_factory=list, max_length=50, description="伏笔列表")


class OutlineCreate(StrictWriteModel):
    """创建大纲请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    nodes: List[OutlineNode] = Field(..., min_length=1, max_length=500, description="大纲节点列表")


class OutlineResponse(BaseModel):
    """大纲响应"""
    id: int
    novel_id: int
    nodes: List["OutlineNodeResponse"]
    created_at: datetime


class OutlineNodeResponse(BaseModel):
    """大纲节点读取模型，允许返回早期未加预算的持久化内容。"""

    chapter: int
    title: str
    plot_points: List[str]
    foreshadowing: List[str] = Field(default_factory=list)


# ========== 内容生成相关模型 ==========

class GenerationRequest(StrictWriteModel):
    """内容生成请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    prompt: str = Field(..., min_length=1, max_length=4000, description="剧情提示词")
    chapter: int = Field(..., gt=0, description="当前章节号")
    current_day: Optional[int] = Field(None, gt=0, description="故事当前天数；未指定时仅按章节限定上下文，并跳过按日时间线检查")
    target_length: int = Field(500, ge=100, le=8000, description="目标字数")


class InitNovelRequest(StrictWriteModel):
    """AI初始化小说设定请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    target_chapters: int = Field(10, ge=1, le=80, description="规划的章节数量")
    theme: Optional[str] = Field(None, max_length=1_000, description="故事主题或补充设定提示")


class StageOutput(BaseModel):
    """单个Agent的输出"""
    agent_type: StageType
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConsistencyCheckResult(BaseModel):
    """一致性检查结果"""
    check_type: ConsistencyCheckType
    is_valid: bool
    violations: List[str] = Field(default_factory=list)


class FinalConsistencyStatus(BaseModel):
    """最终生成稿在一致性重试结束后的明确状态。"""

    status: Literal["passed", "incomplete", "conflict", "conflict_after_retries"]
    has_conflict: bool
    retry_exhausted: bool
    is_complete: bool
    checks_skipped: List[str]
    violations: List[str] = Field(default_factory=list)


class GenerationResponse(BaseModel):
    """内容生成响应"""
    execution: Dict[str, Any] = Field(default_factory=dict)
    novel_id: int
    chapter: int
    final_content: str
    stage_outputs: List[StageOutput]
    consistency_checks: List[ConsistencyCheckResult]
    retry_count: int = 0
    final_consistency: FinalConsistencyStatus
    generated_at: datetime
    worldview_context: List[str] = Field(default_factory=list)
    character_context: List[str] = Field(default_factory=list)
    story_bible_context: List[str] = Field(default_factory=list)
    context_manifest: Dict[str, Any] = Field(default_factory=dict, description="本次实际注入的分层记忆来源与省略原因")
    rag_results: List[Dict[str, Any]] = Field(default_factory=list)
    workflow_trace: Optional[WorkflowTrace] = Field(
        default=None,
        description="本次生成工作流的执行追踪信息，供前端可视化展示",
    )


class InitNovelResponse(BaseModel):
    """AI初始化小说设定响应"""
    novel_id: int
    worldview: str
    main_characters: List[str]
    outline: str
    plot_hooks: List[str]


class IdeaCharacter(BaseModel):
    """自然语言建书时的结构化角色预览。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=300)
    personality: str = Field(min_length=1, max_length=500)
    goal: str = Field(min_length=1, max_length=500)


class IdeaOutlineItem(BaseModel):
    """自然语言建书时的计划大纲节点。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    chapter_number: int = Field(gt=0, strict=True)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1000)
    conflict: str = Field(min_length=1, max_length=1000)
    outcome: str = Field(min_length=1, max_length=1000)


class IdeaArc(BaseModel):
    """全书卷/阶段级结构；长篇按阶段覆盖，不要求逐章展开。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=100)
    chapter_start: int = Field(gt=0, strict=True)
    chapter_end: int = Field(gt=0, strict=True)
    summary: str = Field(min_length=1, max_length=1000)


class IdeaParseRequest(StrictWriteModel):
    """把作者的自然语言想法解析为建书草案，不创建小说或写入数据库。"""
    idea: str = Field(min_length=1, max_length=4_000)
    # 全书预计篇幅属于作者的长期目标，不是一次模型输出的条数上限。
    planned_chapters: int = Field(120, ge=1, le=3_000, strict=True)


class IdeaParseResponse(BaseModel):
    """自然语言建书的可编辑结构化预览。"""
    title: str = Field(min_length=1, max_length=200)
    genre: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=8_000)
    worldview: str = Field(min_length=1, max_length=50_000)
    planned_chapters: int = Field(ge=1, le=3_000, strict=True)
    arcs: List[IdeaArc] = Field(min_length=1, max_length=12)
    characters: List[IdeaCharacter] = Field(min_length=1, max_length=8)
    # 只详列开头可直接开写的章节，后续章节在写作中按卷推进。
    opening_outline: List[IdeaOutlineItem] = Field(min_length=1, max_length=12)
    plot_hooks: List[str] = Field(min_length=1, max_length=12)
    uncertainties: List[str] = Field(default_factory=list, max_length=12)




class PlotOption(BaseModel):
    """剧情走向选项"""
    id: int
    title: str
    summary: str
    impact: Optional[str] = None
    risk: Optional[str] = None


class PlotOptionsRequest(StrictWriteModel):
    """剧情走向选项请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    chapter_id: int = Field(..., gt=0, description="当前章节ID")
    current_content: str = Field(
        ...,
        max_length=MAX_PLOT_OPTIONS_CONTENT_CHARS,
        description="用于判断下一步剧情走向的文本（通常是当前章节或上一章节的结尾）",
    )
    num_options: int = Field(3, ge=1, le=6, description="需要返回的剧情走向数量")


class PlotOptionsResponse(BaseModel):
    """剧情走向选项响应"""
    novel_id: int
    chapter_id: int
    options: List[PlotOption]


class AutoChapterRequest(StrictWriteModel):
    expected_novel_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    expected_chapter_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    """AI自动生成章节请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    base_chapter_id: Optional[int] = Field(
        None,
        gt=0,
        description="作为生成参考的基础章节ID，不传则使用最后一章",
    )
    target_length: int = Field(500, ge=100, le=3000, description="AI生成章节的目标字数")
    theme: Optional[str] = Field(
        None,
        max_length=1000,
        description="本章剧情重点或风格提示，如'推进主线冲突'、'日常轻松番外'等",
    )


class RewriteRequest(StrictWriteModel):
    selection_start: int | None = Field(None, ge=0, description="选区起点，Unicode 字符位置")
    selection_end: int | None = Field(None, gt=0, description="选区终点，不包含该位置")
    expected_novel_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    expected_chapter_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    """局部文本改写请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    chapter_id: Optional[int] = Field(None, gt=0, description="当前章节ID（可选，用于权限校验）")
    original_text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_REWRITE_SOURCE_CHARS,
        description="需要改写的原始文本",
    )
    rewrite_type: Literal["polish", "rewrite", "shorten", "extend"] = Field(
        "polish",
        description="改写类型：polish（润色）/rewrite（重写）/shorten（压缩）/extend（扩写）",
    )
    style_hint: Optional[str] = Field(
        None,
        max_length=1_000,
        description="额外风格提示，例如保持文风不变、偏古风、偏轻松等",
    )
    target_length: Optional[int] = Field(
        None,
        ge=10,
        le=5000,
        description="目标字数（可选，不指定则由模型自动控制长度）",
    )

    @model_validator(mode="after")
    def validate_selection(self):
        if (self.selection_start is None) != (self.selection_end is None):
            raise ValueError("改写选区起止位置必须同时提供")
        if self.selection_start is not None and self.selection_end <= self.selection_start:
            raise ValueError("改写选区终点必须晚于起点")
        return self


class RewriteResponse(BaseModel):
    proposal_id: str | None = None
    execution: Dict[str, Any] = Field(default_factory=dict)
    """局部文本改写响应"""
    rewritten_text: str = Field(..., description="改写后的文本")


class ResearchRequest(StrictWriteModel):
    """资料检索请求"""
    novel_id: Optional[int] = Field(None, gt=0, description="小说ID（可选，用于后续扩展上下文绑定）")
    query: str = Field(
        ...,
        min_length=1,
        max_length=MAX_RESEARCH_QUERY_CHARS,
        description="检索问题或关键词",
    )
    category: Optional[str] = Field(None, max_length=50, description="检索类别，如history/geography/technology")


class ResearchResult(BaseModel):
    """资料检索结果"""
    title: str
    summary: str
    source: str
    url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchResponse(BaseModel):
    """资料检索响应"""
    query: str
    results: List[ResearchResult]


# ========== RAG检索相关模型 ==========

class RAGQuery(StrictWriteModel):
    """RAG检索请求"""
    novel_id: int = Field(..., gt=0, description="小说ID")
    query: str = Field(..., min_length=1, max_length=2000, description="检索查询")
    max_chapter: Optional[int] = Field(None, gt=0, description="最大章节号（用于过滤）")
    top_k: int = Field(3, ge=1, le=20, description="返回Top K结果")


class RAGResult(BaseModel):
    """RAG检索结果"""
    content: str
    metadata: Dict[str, Any]
    score: float


class RAGResponse(BaseModel):
    """RAG检索响应"""
    status: str = "ready"
    reason: str | None = None
    query: str
    results: List[RAGResult]
    retrieval_method: str  # "hybrid", "vector", "bm25"
