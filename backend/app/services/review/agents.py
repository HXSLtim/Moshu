"""审核 Agent 具体实现

包含所有审核 Agent 的详细实现逻辑
"""
from typing import Any, Dict, List, Literal, Optional, TypeVar
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from app.core.config import settings
from app.models.workflow_schemas import AgentWorkflowStep
from app.services.rag import rag_service
from app.services.model.result import parse_model_result
from app.services.context.budget import (
    MAX_CHAT_OUTPUT_CHARS,
    build_previous_chapter_context,
    build_review_content,
)
from loguru import logger
import json


class StrictReviewModel(BaseModel):
    """审核模型输出基类：禁止类型转换与未声明字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class PaceReviewPayload(StrictReviewModel):
    """节奏审核模型输出。"""

    score: int = Field(ge=0, le=100)
    pace_type: Literal["slow", "medium", "fast", "uneven"]
    issues: List[str]
    suggestions: List[str]
    details: Dict[str, Any]


class QualityReviewPayload(StrictReviewModel):
    """质量审核模型输出。"""

    score: int = Field(ge=0, le=100)
    grammar_score: int = Field(ge=0, le=100)
    logic_score: int = Field(ge=0, le=100)
    description_score: int = Field(ge=0, le=100)
    issues: List[str]
    suggestions: List[str]


class PlotCoherencePayload(StrictReviewModel):
    """情节连贯性审核模型输出。"""

    score: int = Field(ge=0, le=100)
    coherence_issues: List[str]
    plot_holes: List[str]
    suggestions: List[str]


class CharacterInconsistencyPayload(StrictReviewModel):
    """角色不一致问题。"""

    type: Literal["性格", "对话", "能力", "关系"]
    description: str = Field(min_length=1)


class CharacterConsistencyPayload(StrictReviewModel):
    """角色一致性审核模型输出。"""

    score: int = Field(ge=0, le=100)
    inconsistencies: List[CharacterInconsistencyPayload]
    suggestions: List[str]


class StyleReviewPayload(StrictReviewModel):
    """文风审核模型输出。"""

    score: int = Field(ge=0, le=100)
    style_type: str = Field(min_length=1)
    consistency_score: int = Field(ge=0, le=100)
    issues: List[str]
    suggestions: List[str]


class FlaggedContentPayload(StrictReviewModel):
    """内容安全命中项。"""

    type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]


class ContentSafetyPayload(StrictReviewModel):
    """内容安全审核模型输出。"""

    is_safe: StrictBool
    risk_level: Literal["low", "medium", "high"]
    flagged_content: List[FlaggedContentPayload]
    suggestions: List[str]


ReviewPayload = TypeVar("ReviewPayload", bound=StrictReviewModel)


def parse_json_response(
    response_text: str,
    result_model: type[ReviewPayload],
) -> Dict[str, Any]:
    """解析并严格校验LLM返回的JSON响应。"""
    try:
        # 提取JSON部分（可能包含markdown代码块）
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        raw_result = json.loads(response_text)
        return result_model.model_validate(raw_result).model_dump()
    except Exception as e:
        logger.error(f"审核结果解析或校验失败: {e}, 原文: {response_text[:200]}")
        raise


async def review_pace_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    章节节奏审核Agent
    
    分析章节的叙事节奏，包括：
    - 情节推进速度
    - 描写与对话的平衡
    - 高潮与平缓的分布
    - 节奏变化的合理性
    """
    logger.info(f"节奏审核Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位专业的小说节奏审核专家。请分析章节的叙事节奏，评估以下维度：

1. **情节推进速度**：是否过快或过慢
2. **描写与对话平衡**：环境描写、心理描写、对话的比例是否合理
3. **高潮与平缓分布**：是否有节奏起伏，避免平铺直叙
4. **节奏变化合理性**：转折是否自然

请以JSON格式返回审核结果：
{{
    "score": 0-100的整数得分,
    "pace_type": "slow/medium/fast/uneven",
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"],
    "details": {{
        "plot_speed": "描述",
        "balance": "描述",
        "rhythm": "描述"
    }}
}}"""),
        ("user", "章节号：{chapter_number}\n\n章节内容：\n{content}\n\n请审核节奏。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({"chapter_number": chapter_number, "content": content})
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, PaceReviewPayload)
        
    except Exception as e:
        logger.error(f"节奏审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    # 记录工作流步骤
    step = AgentWorkflowStep(
        id="pace_review",
        parent_id=None,
        type="agent",
        agent_name="PaceReviewAgent",
        title="章节节奏审核",
        description="分析章节的叙事节奏、情节推进速度和节奏变化",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
            "content_length": len(content),
        },
        output={
            "score": result["score"],
            "pace_type": result["pace_type"],
            "issues_count": len(result["issues"]),
        },
        data_sources={},
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result


async def review_quality_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    内容质量检查Agent
    
    检查：
    - 语法和用词
    - 逻辑合理性
    - 描写质量
    - 表达清晰度
    """
    logger.info(f"质量审核Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位专业的小说质量审核专家。请从以下维度评估章节质量：

1. **语法和用词**（grammar_score）：是否有语法错误、用词不当
2. **逻辑合理性**（logic_score）：情节发展是否符合逻辑
3. **描写质量**（description_score）：环境、人物、动作描写是否生动

请以JSON格式返回：
{{
    "score": 0-100的总体得分,
    "grammar_score": 0-100,
    "logic_score": 0-100,
    "description_score": 0-100,
    "issues": ["具体问题"],
    "suggestions": ["改进建议"]
}}"""),
        ("user", "章节号：{chapter_number}\n\n章节内容：\n{content}\n\n请审核质量。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({"chapter_number": chapter_number, "content": content})
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, QualityReviewPayload)
        
    except Exception as e:
        logger.error(f"质量审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    step = AgentWorkflowStep(
        id="quality_review",
        parent_id=None,
        type="agent",
        agent_name="QualityReviewAgent",
        title="内容质量检查",
        description="检查语法、逻辑和描写质量",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
        },
        output={
            "score": result["score"],
            "grammar_score": result["grammar_score"],
            "logic_score": result["logic_score"],
            "description_score": result["description_score"],
        },
        data_sources={},
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result


async def review_plot_coherence_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    previous_chapters: Optional[List[str]],
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    情节连贯性Agent
    
    检查当前章节与前面章节的连贯性
    """
    logger.info(f"情节连贯性Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    # 如果有前面的章节，进行连贯性检查
    recent_chapters = build_previous_chapter_context(previous_chapters)
    context = "\n\n---\n\n".join(recent_chapters)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位专业的情节连贯性审核专家。请检查当前章节与前面章节的连贯性：

1. **情节衔接**：是否与前文自然衔接
2. **伏笔呼应**：是否有未解决的伏笔或矛盾
3. **时间线一致**：时间顺序是否合理
4. **因果关系**：事件发展是否有合理的因果

请以JSON格式返回：
{{
    "score": 0-100,
    "coherence_issues": ["连贯性问题"],
    "plot_holes": ["情节漏洞"],
    "suggestions": ["改进建议"]
}}"""),
        ("user", "前面章节摘要：\n{previous_context}\n\n当前章节（第{chapter_number}章）：\n{content}\n\n请审核连贯性。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({"chapter_number": chapter_number, "content": content, "previous_context": context})
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, PlotCoherencePayload)
        
    except Exception as e:
        logger.error(f"连贯性审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    step = AgentWorkflowStep(
        id="plot_coherence",
        parent_id=None,
        type="agent",
        agent_name="PlotCoherenceAgent",
        title="情节连贯性检查",
        description="检查章节间的情节连贯性和逻辑一致性",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
            "has_previous_context": bool(previous_chapters),
        },
        output={
            "score": result["score"],
            "issues_count": len(result["coherence_issues"]) + len(result["plot_holes"]),
        },
        data_sources={},
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result


async def review_character_consistency_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    角色一致性Agent
    
    检查角色性格、行为、说话方式是否一致
    """
    logger.info(f"角色一致性Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    # 从RAG检索角色信息
    # 首章没有前文章节，None 会移除过滤并把后续剧情带入审核。
    character_context = []
    if chapter_number > 1:
        character_context = await rag_service.retrieve_character_info(
            novel_id=novel_id, character_name="主角", max_chapter=chapter_number - 1,
        )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位专业的角色一致性审核专家。请检查角色在本章节中的表现是否与之前一致：

1. **性格一致性**：行为是否符合角色性格
2. **说话风格**：对话是否符合角色特点
3. **能力水平**：是否突然变强或变弱
4. **关系变化**：人物关系变化是否合理

角色历史信息：
{character_context}

请以JSON格式返回：
{{
    "score": 0-100,
    "inconsistencies": [
        {{"type": "性格/对话/能力/关系", "description": "具体不一致之处"}}
    ],
    "suggestions": ["改进建议"]
}}"""),
        ("user", "章节号：{chapter_number}\n\n章节内容：\n{content}\n\n请审核角色一致性。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({
            "chapter_number": chapter_number,
            "content": content,
            "character_context": "\n".join(character_context or ["无历史信息"])
        })
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, CharacterConsistencyPayload)
        
    except Exception as e:
        logger.error(f"角色一致性审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    step = AgentWorkflowStep(
        id="character_consistency",
        parent_id=None,
        type="agent",
        agent_name="CharacterConsistencyAgent",
        title="角色一致性检查",
        description="检查角色性格、行为和对话的一致性",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
        },
        output={
            "score": result["score"],
            "inconsistencies_count": len(result["inconsistencies"]),
        },
        data_sources={
            "character_context": character_context[:5] if character_context else [],
        },
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result


async def review_style_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    语言风格Agent
    
    检查语言风格的一致性和质量
    """
    logger.info(f"风格审核Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位专业的文学风格审核专家。请评估章节的语言风格：

1. **风格类型**：现代/古典/诗意/简洁等
2. **风格一致性**：整章风格是否统一
3. **语言质量**：用词是否精准、表达是否优美
4. **可读性**：是否流畅易读

请以JSON格式返回：
{{
    "score": 0-100,
    "style_type": "风格类型描述",
    "consistency_score": 0-100,
    "issues": ["风格问题"],
    "suggestions": ["改进建议"]
}}"""),
        ("user", "章节号：{chapter_number}\n\n章节内容：\n{content}\n\n请审核语言风格。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({"chapter_number": chapter_number, "content": content})
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, StyleReviewPayload)
        
    except Exception as e:
        logger.error(f"风格审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    step = AgentWorkflowStep(
        id="style_review",
        parent_id=None,
        type="agent",
        agent_name="StyleReviewAgent",
        title="语言风格审核",
        description="评估语言风格的一致性和质量",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
        },
        output={
            "score": result["score"],
            "style_type": result["style_type"],
            "consistency_score": result["consistency_score"],
        },
        data_sources={},
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result


async def review_content_safety_agent(
    llm: ChatOpenAI,
    novel_id: int,
    chapter_number: int,
    content: str,
    workflow_steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    内容安全检测Agent
    
    检测敏感内容（简化版，实际应使用专业的内容审核API）
    """
    logger.info(f"内容安全Agent开始工作：章节{chapter_number}")
    content = build_review_content(content)
    
    step_start = datetime.utcnow()
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位内容安全审核专家。请检测章节中是否包含不适当内容：

1. **暴力血腥**：过度暴力描写
2. **色情低俗**：不当性描写
3. **政治敏感**：敏感政治话题
4. **违法犯罪**：美化违法行为

请以JSON格式返回：
{{
    "is_safe": true/false,
    "risk_level": "low/medium/high",
    "flagged_content": [
        {{"type": "类型", "description": "具体内容", "severity": "low/medium/high"}}
    ],
    "suggestions": ["处理建议"]
}}"""),
        ("user", "章节号：{chapter_number}\n\n章节内容：\n{content}\n\n请进行内容安全检测。")
    ])
    
    try:
        chain = prompt | llm
        response = await chain.ainvoke({"chapter_number": chapter_number, "content": content})
        result = parse_json_response(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text, ContentSafetyPayload)
        
    except Exception as e:
        logger.error(f"内容安全审核失败: {e}")
        raise
    
    step_end = datetime.utcnow()
    
    step = AgentWorkflowStep(
        id="content_safety",
        parent_id=None,
        type="agent",
        agent_name="ContentSafetyAgent",
        title="内容安全检测",
        description="检测敏感和不适当内容",
        input={
            "novel_id": novel_id,
            "chapter_number": chapter_number,
        },
        output={
            "is_safe": result["is_safe"],
            "risk_level": result["risk_level"],
            "flagged_count": len(result["flagged_content"]),
        },
        data_sources={},
        llm={
            "model": settings.OPENAI_MODEL_COMPLEX,
            "temperature": 0.3,
        },
        status="completed",
        started_at=step_start,
        finished_at=step_end,
        duration_ms=int((step_end - step_start).total_seconds() * 1000),
    )
    workflow_steps.append(step.model_dump())
    
    return result
