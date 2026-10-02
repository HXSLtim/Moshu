"""单次创作工具：角色生成、分析与优化。

独立的单次模型调用，不走生成工作流；输入输出均经过统一上下文预算，
返回结构化 JSON 供 MCP 能力面(`app.services.mcp.character`)消费。
提示词文本自 generation_workflow.py 原样迁移，仅去除方法级缩进。
"""
import json
from datetime import datetime
from typing import Any, Dict

from langchain.prompts import ChatPromptTemplate
from loguru import logger

from app.core.config import settings
from app.services.context.budget import (
    MAX_CHAT_OUTPUT_CHARS,
    MAX_STORY_CONTEXT_CHARS,
    MAX_WORLDVIEW_CONTEXT_CHARS,
    compact_text,
)
from app.services.model.execution import invoke_model
from app.services.model.provider import create_chat_model
from app.services.model.result import parse_model_result


async def generate_character(context: Dict[str, Any]) -> Dict[str, Any]:
    """AI生成角色"""
    prompt = ChatPromptTemplate.from_template("""
    你是一个专业的小说角色设计师。根据以下信息，创建一个丰富立体的角色。

    小说信息：
    - 标题：{novel_title}
    - 类型：{novel_genre}  
    - 世界观：{worldview}
    
    角色要求：
    {character_requirements}
    
    已有角色：{existing_characters}
    
    请生成一个新角色，包含以下信息：
    1. 姓名（确保不与已有角色重复）
    2. 年龄
    3. 性别
    4. 职业
    5. 外貌描述（100-200字）
    6. 性格特征（100-200字）
    7. 背景故事（200-300字）
    8. 技能列表（3-5项）
    9. 角色弧线（发展轨迹）
    10. 重要性级别（main/secondary/minor）
    
    要求角色符合世界观设定，性格鲜明，有发展潜力。
    
    请以JSON格式返回，字段名使用英文：
    {{
        "name": "角色姓名",
        "age": 年龄数字,
        "gender": "性别",
        "occupation": "职业",
        "appearance": "外貌描述",
        "personality": "性格特征", 
        "background": "背景故事",
        "skills": ["技能1", "技能2", "技能3"],
        "character_arc": "角色弧线",
        "importance_level": "重要性级别"
    }}
    """)
    
    try:
        llm = create_chat_model(
        max_retries=0,
            model=settings.OPENAI_MODEL_COMPLEX,
            temperature=0.8,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        
        existing_characters = context.get("existing_characters") or []
        if isinstance(existing_characters, list):
            existing_characters = "、".join(
                str(item) for item in existing_characters[:100]
            )
        generation_context = {
            "novel_title": str(context.get("novel_title") or "未命名小说"),
            "novel_genre": str(context.get("novel_genre") or "未指定"),
            "worldview": compact_text(
                str(context.get("worldview") or ""),
                MAX_WORLDVIEW_CONTEXT_CHARS,
                keep="head",
            ) or "未设定",
            "character_requirements": compact_text(
                str(context.get("character_requirements") or ""),
                MAX_STORY_CONTEXT_CHARS,
                keep="both",
            ) or "无特别要求",
            "existing_characters": compact_text(
                str(existing_characters),
                MAX_STORY_CONTEXT_CHARS,
                keep="both",
            ) or "暂无",
        }

        chain = prompt | llm
        response = await invoke_model(chain, generation_context)
        
        # 解析JSON响应
        character_data = json.loads(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text)
        
        logger.info(f"AI生成角色: {character_data.get('name', 'Unknown')}")
        return character_data
        
    except Exception as e:
        logger.error(f"AI生成角色失败: {str(e)}")
        raise

async def analyze_character(context: Dict[str, Any]) -> Dict[str, Any]:
    """AI分析角色"""
    prompt = ChatPromptTemplate.from_template("""
    你是一个专业的角色分析师。请对以下角色进行深度分析。

    角色信息：
    - 姓名：{name}
    - 年龄：{age}
    - 性格：{personality}
    - 背景：{background}
    - 角色弧线：{character_arc}
    
    关系网络：
    {relationships}
    
    出场记录：
    {appearances}
    
    分析类型：{analysis_type}
    
    请从以下维度进行分析：
    
    1. 性格分析
    - 核心性格特征
    - 性格优缺点
    - 性格一致性评估
    - 性格发展潜力
    
    2. 发展分析  
    - 角色弧线完整性
    - 成长轨迹合理性
    - 发展节奏评估
    - 未来发展建议
    
    3. 关系分析
    - 关系网络复杂度
    - 关系动态变化
    - 关系冲突潜力
    - 关系发展建议
    
    4. 一致性检查
    - 行为一致性
    - 对话风格一致性
    - 价值观一致性
    - 不一致之处识别
    
    5. 改进建议
    - 角色深度提升
    - 特色强化建议
    - 情节参与度优化
    - 读者印象增强
    
    请以JSON格式返回分析结果：
    {{
        "personality_analysis": {{
            "core_traits": ["特征1", "特征2"],
            "strengths": ["优点1", "优点2"], 
            "weaknesses": ["缺点1", "缺点2"],
            "consistency_score": 评分(1-10),
            "development_potential": "发展潜力描述"
        }},
        "development_analysis": {{
            "arc_completeness": 评分(1-10),
            "growth_trajectory": "成长轨迹评估",
            "pacing_assessment": "节奏评估",
            "future_suggestions": ["建议1", "建议2"]
        }},
        "relationship_analysis": {{
            "network_complexity": 评分(1-10),
            "dynamic_changes": "关系变化分析",
            "conflict_potential": "冲突潜力评估",
            "development_suggestions": ["建议1", "建议2"]
        }},
        "consistency_check": {{
            "behavior_consistency": 评分(1-10),
            "dialogue_consistency": 评分(1-10),
            "value_consistency": 评分(1-10),
            "inconsistencies": ["不一致1", "不一致2"]
        }},
        "improvement_suggestions": [
            "改进建议1",
            "改进建议2", 
            "改进建议3"
        ],
        "overall_score": 总体评分(1-10),
        "summary": "总体评价摘要"
    }}
    """)
    
    try:
        llm = create_chat_model(
        max_retries=0,
            model=settings.OPENAI_MODEL_COMPLEX,
            temperature=0.3,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        
        # 格式化关系和出场信息
        relationships = (context.get('relationships') or [])[:50]
        relationships_str = "\n".join([
            f"- 与{rel['target']}的{rel['type']}关系（强度：{rel['strength']}/10）"
            for rel in relationships
        ]) if relationships else "暂无关系记录"
        relationships_str = compact_text(
            relationships_str,
            MAX_STORY_CONTEXT_CHARS,
            keep="both",
        )
        
        appearances = (context.get('appearances') or [])[-50:]
        appearances_str = "\n".join([
            f"- 第{app['chapter']}章：{app['type']}出场（重要性：{app['importance']}/10）"
            for app in appearances
        ]) if appearances else "暂无出场记录"
        appearances_str = compact_text(
            appearances_str,
            MAX_STORY_CONTEXT_CHARS,
            keep="tail",
        )

        character_context = context['character']
        
        analysis_context = {
            'name': str(character_context.get('name') or '未命名角色')[:100],
            'age': character_context.get('age'),
            'personality': compact_text(
                str(character_context.get('personality') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'background': compact_text(
                str(character_context.get('background') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'character_arc': compact_text(
                str(character_context.get('character_arc') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'relationships': relationships_str,
            'appearances': appearances_str,
            'analysis_type': compact_text(
                str(context.get('analysis_type') or 'comprehensive'),
                50,
                keep='head',
            ),
        }
        
        chain = prompt | llm
        response = await invoke_model(chain, analysis_context)
        
        # 解析JSON响应
        analysis_result = json.loads(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text)
        analysis_result['analysis_timestamp'] = datetime.utcnow().isoformat()
        
        logger.info(f"AI角色分析完成: {context['character']['name']}")
        return analysis_result
        
    except Exception as e:
        logger.error(f"AI角色分析失败: {str(e)}")
        raise

async def optimize_character(context: Dict[str, Any]) -> Dict[str, Any]:
    """AI优化角色"""
    prompt = ChatPromptTemplate.from_template("""
    你是一个专业的角色优化师。请根据优化目标，为角色提供具体的优化建议。

    当前角色：
    - 姓名：{name}
    - 性格：{personality}
    - 背景：{background}
    - 技能：{skills}
    - 角色弧线：{character_arc}
    
    优化目标：
    {goals}
    
    需要保持的特征：
    {preserve}
    
    请提供以下优化建议：
    
    1. 性格优化
    - 保持核心特征的同时，如何增加层次感
    - 如何平衡优缺点，使角色更真实
    - 性格细节的丰富化建议
    
    2. 背景优化
    - 背景故事的深化方向
    - 如何增加背景与性格的关联性
    - 背景中可挖掘的情节点
    
    3. 技能优化
    - 技能体系的完善
    - 技能与角色定位的匹配度
    - 新技能的添加建议
    
    4. 弧线优化
    - 角色发展轨迹的改进
    - 关键转折点的设计
    - 成长节奏的调整
    
    5. 具体修改建议
    - 哪些内容需要修改
    - 具体的修改方案
    - 修改后的预期效果
    
    请以JSON格式返回优化建议：
    {{
        "personality_optimization": {{
            "layering_suggestions": ["建议1", "建议2"],
            "balance_improvements": ["改进1", "改进2"],
            "detail_enhancements": ["细节1", "细节2"]
        }},
        "background_optimization": {{
            "deepening_directions": ["方向1", "方向2"],
            "personality_connections": ["关联1", "关联2"],
            "plot_potentials": ["情节点1", "情节点2"]
        }},
        "skills_optimization": {{
            "system_improvements": ["改进1", "改进2"],
            "positioning_match": "匹配度评估",
            "new_skills_suggestions": ["新技能1", "新技能2"]
        }},
        "arc_optimization": {{
            "trajectory_improvements": ["改进1", "改进2"],
            "key_turning_points": ["转折点1", "转折点2"],
            "pacing_adjustments": ["调整1", "调整2"]
        }},
        "specific_modifications": {{
            "content_to_modify": ["内容1", "内容2"],
            "modification_plans": ["方案1", "方案2"],
            "expected_effects": ["效果1", "效果2"]
        }},
        "optimization_priority": ["优先级1", "优先级2", "优先级3"],
        "confidence_score": 置信度评分(0.0-1.0),
        "reasoning": "优化理由和逻辑"
    }}
    """)
    
    try:
        llm = create_chat_model(
        max_retries=0,
            model=settings.OPENAI_MODEL_COMPLEX,
            temperature=0.5,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        )
        
        # 格式化上下文
        character_context = context['character']
        optimization_context = {
            'name': str(character_context.get('name') or '未命名角色')[:100],
            'personality': compact_text(
                str(character_context.get('personality') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'background': compact_text(
                str(character_context.get('background') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'character_arc': compact_text(
                str(character_context.get('character_arc') or ''),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'goals': compact_text(
                "\n".join([f"- {goal}" for goal in context['goals']]),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'preserve': compact_text(
                "\n".join([f"- {trait}" for trait in context['preserve']]),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
            'skills': compact_text(
                ", ".join(str(item) for item in character_context.get('skills', [])),
                MAX_STORY_CONTEXT_CHARS,
                keep='both',
            ),
        }
        
        chain = prompt | llm
        response = await invoke_model(chain, optimization_context)
        
        # 解析JSON响应
        optimization_result = json.loads(parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text)
        
        logger.info(f"AI角色优化完成: {context['character']['name']}")
        return optimization_result
        
    except Exception as e:
        logger.error(f"AI角色优化失败: {str(e)}")
        raise
