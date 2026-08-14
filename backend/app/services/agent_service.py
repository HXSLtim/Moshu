"""多Agent服务

实现基于LangGraph的三Agent协作工作流，并在内部构建Agent工作流追踪，
便于前端可视化展示各个Agent节点的执行过程和数据流。
"""
from typing import TypedDict, Dict, Any, List
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from app.core.config import settings
from app.models.schemas import (
    GenerationRequest,
    GenerationResponse,
    AgentOutput,
    AgentType,
    ConsistencyCheckResult,
    ConsistencyCheckType,
    FinalConsistencyStatus,
)
from app.models.workflow_schemas import AgentWorkflowStep, AgentWorkflowTrace
from app.services.rag_service import rag_service
from app.services.consistency_service import consistency_service
from app.services.context_budget import (
    MAX_STORY_CONTEXT_CHARS,
    MAX_WORLDVIEW_CONTEXT_CHARS,
    build_prompt_trace_summary,
    build_rag_query,
    compact_text,
    ensure_generation_prompt_budget,
)
from loguru import logger
from datetime import datetime
import json


MAX_GENERATION_RETRIES = 2


def _build_final_consistency_status(
    consistency_result: Dict[str, Any],
    retry_count: int,
) -> FinalConsistencyStatus:
    """把最终一次检查转成前端可直接判定的状态。"""
    has_conflict = bool(consistency_result.get("has_conflict", False))
    checks_skipped = list(
        dict.fromkeys(str(item) for item in consistency_result.get("checks_skipped", []))
    )
    raw_is_complete = consistency_result.get("is_complete")
    is_complete = (
        bool(raw_is_complete) and not checks_skipped
        if raw_is_complete is not None
        else not checks_skipped
    )
    retry_exhausted = has_conflict and retry_count >= MAX_GENERATION_RETRIES
    if retry_exhausted:
        final_status = "conflict_after_retries"
    elif has_conflict:
        final_status = "conflict"
    elif not is_complete:
        final_status = "incomplete"
    else:
        final_status = "passed"
    return FinalConsistencyStatus(
        status=final_status,
        has_conflict=has_conflict,
        retry_exhausted=retry_exhausted,
        is_complete=is_complete,
        checks_skipped=checks_skipped,
        violations=[str(item) for item in consistency_result.get("violations", [])],
    )


def _build_consistency_checks(
    consistency_result: Dict[str, Any],
) -> List[ConsistencyCheckResult]:
    """仅序列化真实执行过的检查层。

    `ConsistencyCheckResult.is_valid` 只能表达布尔值，无法承载“未执行”。
    跳过的层保留在 workflow trace 和 `checks_skipped` 中，不伪造成通过结果。
    """
    layer_results = consistency_result.get("layer_results", {}) or {}
    checks: List[ConsistencyCheckResult] = []

    rule_layer = layer_results.get("rule_engine") or {}
    if rule_layer.get("status") == "completed":
        checks.append(
            ConsistencyCheckResult(
                check_type=ConsistencyCheckType.RULE_ENGINE,
                is_valid=rule_layer.get("is_valid") is True,
                violations=list(rule_layer.get("violations", [])),
            )
        )

    graph_layer = layer_results.get("knowledge_graph") or {}
    if graph_layer.get("status") == "completed":
        checks.append(
            ConsistencyCheckResult(
                check_type=ConsistencyCheckType.KNOWLEDGE_GRAPH,
                is_valid=graph_layer.get("is_valid") is True,
                violations=list(graph_layer.get("violations", [])),
            )
        )

    timeline_layer = layer_results.get("timeline") or {}
    if timeline_layer.get("status") == "completed":
        timeline_is_valid = timeline_layer.get("is_valid") is True
        timeline_violations: List[str] = []
        if not timeline_is_valid and timeline_layer.get("reason"):
            timeline_violations = [str(timeline_layer["reason"])]
        checks.append(
            ConsistencyCheckResult(
                check_type=ConsistencyCheckType.TIMELINE,
                is_valid=timeline_is_valid,
                violations=timeline_violations,
            )
        )

    emotion_layer = layer_results.get("emotion_state") or {}
    if emotion_layer.get("status") == "completed":
        checks.append(
            ConsistencyCheckResult(
                check_type=ConsistencyCheckType.EMOTION,
                is_valid=emotion_layer.get("is_valid") is True,
                violations=list(emotion_layer.get("violations", [])),
            )
        )

    return checks


# ========== 定义LangGraph状态 ==========

class NovelGenerationState(TypedDict):
    """小说生成工作流状态"""
    # 输入
    novel_id: int
    prompt: str
    chapter: int
    current_day: int
    target_length: int

    # Agent输出
    worldview_output: str
    character_output: str
    plot_output: str

    # 检索到的上下文
    worldview_context: List[str]
    character_context: List[str]

    # 一致性检查结果
    consistency_result: Dict[str, Any]

    # 重试次数
    retry_count: int

    # 工作流步骤（序列化后的AgentWorkflowStep字典列表）
    workflow_steps: List[Dict[str, Any]]


# ========== Agent服务类 ==========

class AgentService:
    """多Agent服务类"""

    def __init__(self):
        """初始化Agent服务"""
        # 初始化LLM
        self.llm_complex = ChatOpenAI(
            model=settings.OPENAI_MODEL_COMPLEX,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            temperature=0.8,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.llm_simple = ChatOpenAI(
            model=settings.OPENAI_MODEL_SIMPLE,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            temperature=0.7,
            max_tokens=min(settings.LLM_MAX_OUTPUT_TOKENS, 1024),
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )

        # 构建工作流图
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """构建LangGraph工作流"""
        # 创建状态图
        workflow = StateGraph(NovelGenerationState)

        # 添加节点
        workflow.add_node("retrieve_context", self._retrieve_context)
        workflow.add_node("agent_a_worldview", self._agent_a_worldview)
        workflow.add_node("agent_b_character", self._agent_b_character)
        workflow.add_node("agent_c_plot", self._agent_c_plot)
        workflow.add_node("consistency_check", self._consistency_check)
        workflow.add_node("increment_retry", self._increment_retry)

        # 定义执行顺序
        workflow.set_entry_point("retrieve_context")
        workflow.add_edge("retrieve_context", "agent_a_worldview")
        workflow.add_edge("agent_a_worldview", "agent_b_character")
        workflow.add_edge("agent_b_character", "agent_c_plot")
        workflow.add_edge("agent_c_plot", "consistency_check")

        # 条件分支：一致性检查失败则重试
        workflow.add_conditional_edges(
            "consistency_check",
            self._should_retry,
            {
                "retry": "increment_retry",
                "end": END
            }
        )
        workflow.add_edge("increment_retry", "agent_c_plot")

        return workflow.compile()

    async def _retrieve_context(self, state: NovelGenerationState) -> Dict:
        """
        检索上下文节点
        从RAG中检索世界观和角色信息
        """
        logger.info(
            "检索上下文：小说{}，章节{}，提示词长度={}",
            state["novel_id"],
            state["chapter"],
            len(state["prompt"]),
        )

        # 为避免剧透，RAG只检索当前章节及之前的内容
        current_chapter = state.get("chapter", 1)
        max_chapter = current_chapter if current_chapter > 0 else None

        # 检索世界观相关内容
        step_start = datetime.utcnow()
        worldview_context = await rag_service.retrieve_worldview(
            novel_id=state["novel_id"],
            query=build_rag_query(state["prompt"]),
            max_chapter=max_chapter,
        )

        # 检索角色相关内容（假设提示词中包含角色名）
        # TODO: 实际应该通过NER提取角色名
        character_context = await rag_service.retrieve_character_info(
            novel_id=state["novel_id"],
            character_name="主角",  # 简化处理
            max_chapter=max_chapter,
        )
        step_end = datetime.utcnow()

        # 记录工作流步骤
        steps = list(state.get("workflow_steps", []))
        retrieve_step = AgentWorkflowStep(
            id="retrieve_context",
            parent_id=None,
            type="rag",
            agent_name="RAGService",
            title="检索上下文",
            description="从RAG中检索世界观和角色相关上下文，避免剧透。",
            input={
                "novel_id": state["novel_id"],
                "chapter": state["chapter"],
                **build_prompt_trace_summary(state["prompt"]),
                "max_chapter": max_chapter,
            },
            output={
                "worldview_chunks": len(worldview_context or []),
                "character_chunks": len(character_context or []),
            },
            data_sources={
                "worldview_context": worldview_context[:5],
                "character_context": character_context[:5],
            },
            llm={},
            status="completed",
            started_at=step_start,
            finished_at=step_end,
            duration_ms=int((step_end - step_start).total_seconds() * 1000),
        )
        steps.append(retrieve_step.model_dump())

        return {
            "worldview_context": worldview_context,
            "character_context": character_context,
            "workflow_steps": steps,
        }

    async def _agent_a_worldview(self, state: NovelGenerationState) -> Dict:
        """
        Agent A：世界观描写
        专注于环境渲染、氛围营造、魔法体系描写
        """
        logger.info("Agent A（世界观）开始工作")

        # 构建提示词
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位专业的小说世界观描写专家。你的任务是根据剧情提示，描写场景的环境、氛围和相关的世界观元素（如魔法、科技等）。

要求：
1. 专注于环境和氛围的渲染
2. 融入世界观设定（魔法体系、地理环境等）
3. 控制在150-200字
4. 不要涉及角色对话和具体剧情
5. 直接描写环境，严禁使用"这里是..."、"场景展示了..."等说明性语言，沉浸式描写

世界观上下文：
{worldview_context}
"""),
            ("user", "剧情提示：{prompt}\n\n请描写场景的世界观和环境氛围。")
        ])

        # 调用LLM
        step_start = datetime.utcnow()
        chain = prompt | self.llm_simple
        response = await chain.ainvoke({
            "prompt": state["prompt"],
            "worldview_context": "\n".join(state.get("worldview_context", ["无相关世界观信息"]))
        })
        step_end = datetime.utcnow()

        worldview_output = response.content
        logger.info(f"Agent A输出：{worldview_output[:50]}...")

        steps = list(state.get("workflow_steps", []))
        step = AgentWorkflowStep(
            id="agent_a_worldview",
            parent_id="retrieve_context",
            type="llm",
            agent_name="AgentAWorldview",
            title="世界观描写Agent",
            description="基于检索到的世界观上下文生成环境与氛围描写。",
            input={
                **build_prompt_trace_summary(state["prompt"]),
                "target_length_hint": "150-200",
            },
            output={
                "preview": worldview_output[:80],
                "length": len(worldview_output),
            },
            data_sources={
                "worldview_context": state.get("worldview_context", [])[:5],
            },
            llm={
                "model": settings.OPENAI_MODEL_SIMPLE,
                "temperature": 0.7,
            },
            status="completed",
            started_at=step_start,
            finished_at=step_end,
            duration_ms=int((step_end - step_start).total_seconds() * 1000),
        )
        steps.append(step.model_dump())

        return {"worldview_output": worldview_output, "workflow_steps": steps}

    async def _agent_b_character(self, state: NovelGenerationState) -> Dict:
        """
        Agent B：角色对话和描写
        专注于符合角色性格的对话、心理活动、动作描写
        """
        logger.info("Agent B（角色）开始工作")

        # 构建提示词
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位专业的小说角色描写专家。你的任务是根据剧情提示和世界观描写，创作符合角色性格的对话、心理活动和动作描写。

要求：
1. 严格遵循角色性格设定
2. 对话要符合角色说话风格
3. 心理活动要真实细腻
4. 控制在200-250字
5. 基于以下世界观描写继续创作
6. 直接描写对话和动作，严禁使用"他想表达..."、"她感到..."等概括性语言，要通过细节展示

角色信息：
{character_context}

世界观描写：
{worldview_output}
"""),
            ("user", "剧情提示：{prompt}\n\n请创作角色的对话、心理和动作描写。")
        ])

        # 调用LLM
        step_start = datetime.utcnow()
        chain = prompt | self.llm_simple
        response = await chain.ainvoke({
            "prompt": state["prompt"],
            "worldview_output": state["worldview_output"],
            "character_context": "\n".join(state.get("character_context", ["无相关角色信息"]))
        })
        step_end = datetime.utcnow()

        character_output = response.content
        logger.info(f"Agent B输出：{character_output[:50]}...")

        steps = list(state.get("workflow_steps", []))
        step = AgentWorkflowStep(
            id="agent_b_character",
            parent_id="agent_a_worldview",
            type="llm",
            agent_name="AgentBCharacter",
            title="角色描写Agent",
            description="基于世界观描写和角色信息生成对话与心理描写。",
            input={
                **build_prompt_trace_summary(state["prompt"]),
                "worldview_preview": state.get("worldview_output", "")[:80],
            },
            output={
                "preview": character_output[:80],
                "length": len(character_output),
            },
            data_sources={
                "character_context": state.get("character_context", [])[:5],
            },
            llm={
                "model": settings.OPENAI_MODEL_SIMPLE,
                "temperature": 0.7,
            },
            status="completed",
            started_at=step_start,
            finished_at=step_end,
            duration_ms=int((step_end - step_start).total_seconds() * 1000),
        )
        steps.append(step.model_dump())

        return {"character_output": character_output, "workflow_steps": steps}

    async def _agent_c_plot(self, state: NovelGenerationState) -> Dict:
        """
        Agent C：剧情控制
        整合世界观和角色内容，推进剧情，埋设伏笔
        """
        logger.info("Agent C（剧情控制）开始工作")

        # 检查是否有一致性违规需要修正
        consistency_result = state.get("consistency_result", {})
        has_conflict = consistency_result.get("has_conflict", False)
        retry_count = state.get("retry_count", 0)
        
        # 构建基础系统提示词
        system_prompt = """你是一位专业的小说剧情控制专家。你的任务是整合世界观描写和角色内容，推进剧情发展，并适当埋设伏笔。

要求：
1. 自然融合世界观描写和角色内容
2. 推进剧情，不要拖沓
3. 适当埋设伏笔（如果合适）
4. 控制在总计{target_length}字左右
5. 使用自然的段落分行，适当换行，便于阅读，不要刻意把所有内容挤在一整段里
6. 严禁对剧情进行总结、概述或评价，必须直接描写具体的场景、动作和对话
7. 不要出现"总而言之"、"综上所述"、"这一章讲述了"等总结性词语
8. 结尾不要强行升华或总结，保持剧情的自然流动，留有悬念

世界观描写：
{worldview_output}

角色描写：
{character_output}"""

        # 如果是重试，添加一致性违规信息
        if has_conflict and retry_count > 0:
            violations = consistency_result.get("violations", [])
            if violations:
                violation_text = "\n".join([f"- {v}" for v in violations])
                logger.info(f"Agent C 重试第{retry_count}次，违规信息：{violations}")
                system_prompt += f"""

⚠️ 重要提醒：上一次生成的内容存在一致性问题，请在本次生成中避免以下违规：
{violation_text}

请特别注意：
- 时间线的合理性（角色移动、事件发生的时间间隔）
- 地理位置的逻辑性（角色移动距离与时间的匹配）
- 角色行为的一致性（不要违反角色设定）
- 世界观设定的一致性（不要违反已建立的规则）"""

        # 构建提示词
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "剧情提示：{prompt}\n\n请整合以上内容，输出完整的小说段落。")
        ])

        # 使用复杂模型
        step_start = datetime.utcnow()
        chain = prompt | self.llm_complex
        response = await chain.ainvoke({
            "prompt": state["prompt"],
            "worldview_output": state["worldview_output"],
            "character_output": state["character_output"],
            "target_length": state["target_length"]
        })
        step_end = datetime.utcnow()

        plot_output = response.content
        logger.info(f"Agent C输出：{plot_output[:50]}...（共{len(plot_output)}字）")

        steps = list(state.get("workflow_steps", []))
        step = AgentWorkflowStep(
            id=f"agent_c_plot_{retry_count}",
            parent_id=(
                "agent_b_character"
                if retry_count == 0
                else f"consistency_check_{retry_count - 1}"
            ),
            type="llm",
            agent_name="AgentCPlot",
            title="剧情控制Agent",
            description="整合世界观与角色内容，生成最终剧情输出。",
            input={
                **build_prompt_trace_summary(state["prompt"]),
                "target_length": state["target_length"],
            },
            output={
                "preview": plot_output[:80],
                "length": len(plot_output),
            },
            data_sources={},
            llm={
                "model": settings.OPENAI_MODEL_COMPLEX,
                "temperature": 0.8,
            },
            status="completed",
            started_at=step_start,
            finished_at=step_end,
            duration_ms=int((step_end - step_start).total_seconds() * 1000),
        )
        steps.append(step.model_dump())

        return {"plot_output": plot_output, "workflow_steps": steps}

    async def _consistency_check(self, state: NovelGenerationState) -> Dict:
        """
        一致性检查节点
        验证生成的内容是否符合世界观规则、角色性格等
        """
        logger.info("执行一致性检查")

        step_start = datetime.utcnow()

        # 调用一致性检查服务
        result = await consistency_service.check_content(
            novel_id=state["novel_id"],
            content=state["plot_output"],
            chapter=state["chapter"],
            current_day=state["current_day"]
        )
        step_end = datetime.utcnow()

        steps = list(state.get("workflow_steps", []))
        retry_count = state.get("retry_count", 0)
        consistency_step = AgentWorkflowStep(
            id=f"consistency_check_{retry_count}",
            parent_id=f"agent_c_plot_{retry_count}",
            type="consistency",
            agent_name="ConsistencyService",
            title="一致性检查",
            description="调用一致性检查服务验证生成内容是否违反世界观或角色设定。",
            input={
                "novel_id": state["novel_id"],
                "chapter": state["chapter"],
                "current_day": state["current_day"],
            },
            output={
                "has_conflict": result.get("has_conflict", False),
                "violation_count": len(result.get("violations", [])),
                "is_complete": result.get("is_complete", False),
                "checks_skipped": list(result.get("checks_skipped", [])),
            },
            data_sources={
                "consistency_layer_results": result.get("layer_results", {}),
                "consistency_workflow_trace": result.get("workflow_trace"),
            },
            llm={},
            status="completed",
            started_at=step_start,
            finished_at=step_end,
            duration_ms=int((step_end - step_start).total_seconds() * 1000),
        )
        steps.append(consistency_step.model_dump())

        return {"consistency_result": result, "workflow_steps": steps}

    def _should_retry(self, state: NovelGenerationState) -> str:
        """
        判断是否需要重试

        Returns:
            "retry" 或 "end"
        """
        result = state.get("consistency_result", {})
        has_conflict = result.get("has_conflict", False)
        retry_count = state.get("retry_count", 0)

        # 如果有冲突且重试次数小于2次，则重试
        # 注意：最多重试2次（总共3次生成），防止无限重试
        if has_conflict and retry_count < MAX_GENERATION_RETRIES:
            logger.warning(f"检测到一致性冲突，执行第{retry_count + 1}次重试")
            return "retry"

        if has_conflict:
            logger.warning(f"重试次数已达上限（共{retry_count + 1}次生成），仍存在一致性冲突，将返回最后生成的内容")
            # 不再重试，返回最后生成的内容
            logger.info(f"最后一次生成的内容长度：{len(state.get('plot_output', ''))}字")

        return "end"

    def _increment_retry(self, state: NovelGenerationState) -> Dict[str, int]:
        """通过正式图节点写回重试次数，避免在条件路由中修改临时状态。"""

        retry_count = state.get("retry_count", 0) + 1
        return {"retry_count": retry_count}

    async def generate_content(
        self,
        request: GenerationRequest
    ) -> GenerationResponse:
        """
        生成小说内容

        Args:
            request: 生成请求

        Returns:
            生成响应
        """
        bounded_prompt = ensure_generation_prompt_budget(request.prompt)
        logger.info(
            "开始生成内容：小说{}，章节{}，提示词长度={}",
            request.novel_id,
            request.chapter,
            len(bounded_prompt),
        )

        # 准备初始状态
        initial_state: NovelGenerationState = {
            "novel_id": request.novel_id,
            "prompt": bounded_prompt,
            "chapter": request.chapter,
            "current_day": request.current_day,
            "target_length": request.target_length,
            "worldview_output": "",
            "character_output": "",
            "plot_output": "",
            "worldview_context": [],
            "character_context": [],
            "consistency_result": {},
            "retry_count": 0,
            "workflow_steps": [],
        }

        # 执行工作流
        final_state = await self.workflow.ainvoke(initial_state)

        # 从一致性结果中构建结构化的一致性检查列表
        consistency_result = final_state.get("consistency_result", {}) or {}
        consistency_checks = _build_consistency_checks(consistency_result)

        # 构建Agent工作流追踪
        steps_data = final_state.get("workflow_steps", []) or []
        steps: List[AgentWorkflowStep] = []
        for item in steps_data:
            try:
                steps.append(AgentWorkflowStep(**item))
            except Exception:
                # 忽略单个步骤解析错误，避免影响整体响应
                logger.warning("解析AgentWorkflowStep失败，已跳过一条步骤数据")
                continue

        workflow_trace = AgentWorkflowTrace(
            run_id=f"agent-generate-{request.novel_id}-{request.chapter}-{int(datetime.utcnow().timestamp() * 1000)}",
            trigger="generation.generate_content",
            novel_id=request.novel_id,
            chapter_id=request.chapter,
            user_id=None,
            summary=f"小说{request.novel_id} 第{request.chapter}章的多Agent内容生成",
            steps=steps,
        )

        # 构建响应
        response = GenerationResponse(
            novel_id=request.novel_id,
            chapter=request.chapter,
            final_content=final_state["plot_output"],
            agent_outputs=[
                AgentOutput(
                    agent_type=AgentType.WORLDVIEW,
                    content=final_state["worldview_output"],
                ),
                AgentOutput(
                    agent_type=AgentType.CHARACTER,
                    content=final_state["character_output"],
                ),
                AgentOutput(
                    agent_type=AgentType.PLOT,
                    content=final_state["plot_output"],
                ),
            ],
            consistency_checks=consistency_checks,
            retry_count=final_state["retry_count"],
            final_consistency=_build_final_consistency_status(
                consistency_result,
                final_state["retry_count"],
            ),
            generated_at=datetime.now(),
            worldview_context=final_state.get("worldview_context", []),
            character_context=final_state.get("character_context", []),
            workflow_trace=workflow_trace,
        )

        logger.info(f"内容生成完成，共{len(response.final_content)}字")
        return response

    async def generate_content_stream(
        self,
        request: GenerationRequest
    ):
        """
        流式生成小说内容，yield事件
        """
        bounded_prompt = ensure_generation_prompt_budget(request.prompt)
        logger.info(
            "开始流式生成内容：小说{}，章节{}，提示词长度={}",
            request.novel_id,
            request.chapter,
            len(bounded_prompt),
        )

        # 准备初始状态
        initial_state: NovelGenerationState = {
            "novel_id": request.novel_id,
            "prompt": bounded_prompt,
            "chapter": request.chapter,
            "current_day": request.current_day,
            "target_length": request.target_length,
            "worldview_output": "",
            "character_output": "",
            "plot_output": "",
            "worldview_context": [],
            "character_context": [],
            "consistency_result": {},
            "retry_count": 0,
            "workflow_steps": [],
        }

        # 记录合并后的状态
        final_state = initial_state.copy()

        # yield initial event
        yield {"type": "agent", "agent": "System", "status": "初始化完成", "data": None}

        async for output in self.workflow.astream(initial_state):
            for node_name, node_data in output.items():
                # 更新最终状态
                final_state.update(node_data)
                
                # 根据节点名称发送事件
                if node_name == "retrieve_context":
                    yield {"type": "agent", "agent": "RAG", "status": "上下文检索完成", "data": {"worldview_chunks": len(node_data.get("worldview_context", [])), "character_chunks": len(node_data.get("character_context", []))}}
                    yield {"type": "agent", "agent": "Agent A", "status": "正在构思世界观...", "data": None}
                
                elif node_name == "agent_a_worldview":
                    yield {"type": "agent", "agent": "Agent A", "status": "世界观描写完成", "data": {"preview": node_data.get("worldview_output", "")[:50]}}
                    yield {"type": "agent", "agent": "Agent B", "status": "正在刻画角色...", "data": None}
                
                elif node_name == "agent_b_character":
                    yield {"type": "agent", "agent": "Agent B", "status": "角色描写完成", "data": {"preview": node_data.get("character_output", "")[:50]}}
                    yield {"type": "agent", "agent": "Agent C", "status": "正在生成剧情...", "data": None}
                
                elif node_name == "agent_c_plot":
                    yield {"type": "agent", "agent": "Agent C", "status": "剧情生成完成", "data": {"preview": node_data.get("plot_output", "")[:50]}}
                    yield {"type": "agent", "agent": "Consistency", "status": "正在检查一致性...", "data": None}
                
                elif node_name == "consistency_check":
                    result = node_data.get("consistency_result", {})
                    has_conflict = result.get("has_conflict", False)
                    if has_conflict:
                        retry_count = final_state.get("retry_count", 0)
                        status = (
                            "发现冲突，已达重试上限"
                            if retry_count >= MAX_GENERATION_RETRIES
                            else "发现冲突，准备重试"
                        )
                        yield {
                            "type": "agent",
                            "agent": "Consistency",
                            "status": status,
                            "data": {"violations": result.get("violations", [])},
                        }
                    elif not result.get("is_complete", False):
                        yield {
                            "type": "agent",
                            "agent": "Consistency",
                            "status": "已完成可用检查，部分检查已跳过",
                            "data": {"checks_skipped": result.get("checks_skipped", [])},
                        }
                    else:
                        yield {
                            "type": "agent",
                            "agent": "Consistency",
                            "status": "检查通过",
                            "data": None,
                        }

        # 从一致性结果中构建结构化的一致性检查列表
        consistency_result = final_state.get("consistency_result", {}) or {}
        consistency_checks = _build_consistency_checks(consistency_result)

        # 构建Agent工作流追踪
        steps_data = final_state.get("workflow_steps", []) or []
        steps: List[AgentWorkflowStep] = []
        for item in steps_data:
            try:
                steps.append(AgentWorkflowStep(**item))
            except Exception:
                logger.warning("解析AgentWorkflowStep失败，已跳过一条步骤数据")
                continue

        workflow_trace = AgentWorkflowTrace(
            run_id=f"agent-generate-{request.novel_id}-{request.chapter}-{int(datetime.utcnow().timestamp() * 1000)}",
            trigger="generation.generate_content_stream",
            novel_id=request.novel_id,
            chapter_id=request.chapter,
            user_id=None,
            summary=f"小说{request.novel_id} 第{request.chapter}章的多Agent内容生成",
            steps=steps,
        )

        # 构建响应
        response = GenerationResponse(
            novel_id=request.novel_id,
            chapter=request.chapter,
            final_content=final_state["plot_output"],
            agent_outputs=[
                AgentOutput(
                    agent_type=AgentType.WORLDVIEW,
                    content=final_state["worldview_output"],
                ),
                AgentOutput(
                    agent_type=AgentType.CHARACTER,
                    content=final_state["character_output"],
                ),
                AgentOutput(
                    agent_type=AgentType.PLOT,
                    content=final_state["plot_output"],
                ),
            ],
            consistency_checks=consistency_checks,
            retry_count=final_state["retry_count"],
            final_consistency=_build_final_consistency_status(
                consistency_result,
                final_state["retry_count"],
            ),
            generated_at=datetime.now(),
            worldview_context=final_state.get("worldview_context", []),
            character_context=final_state.get("character_context", []),
            workflow_trace=workflow_trace,
        )

        logger.info(f"流式内容生成完成，共{len(response.final_content)}字")
        yield {"type": "final_response", "data": response}
    
    async def generate_character(self, context: Dict[str, Any]) -> Dict[str, Any]:
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
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.8,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
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
            response = await chain.ainvoke(generation_context)
            
            # 解析JSON响应
            character_data = json.loads(response.content)
            
            logger.info(f"AI生成角色: {character_data.get('name', 'Unknown')}")
            return character_data
            
        except Exception as e:
            logger.error(f"AI生成角色失败: {str(e)}")
            raise
    
    async def analyze_character(self, context: Dict[str, Any]) -> Dict[str, Any]:
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
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.3,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
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
            response = await chain.ainvoke(analysis_context)
            
            # 解析JSON响应
            analysis_result = json.loads(response.content)
            analysis_result['analysis_timestamp'] = datetime.utcnow().isoformat()
            
            logger.info(f"AI角色分析完成: {context['character']['name']}")
            return analysis_result
            
        except Exception as e:
            logger.error(f"AI角色分析失败: {str(e)}")
            raise
    
    async def optimize_character(self, context: Dict[str, Any]) -> Dict[str, Any]:
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
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.5,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
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
            response = await chain.ainvoke(optimization_context)
            
            # 解析JSON响应
            optimization_result = json.loads(response.content)
            
            logger.info(f"AI角色优化完成: {context['character']['name']}")
            return optimization_result
            
        except Exception as e:
            logger.error(f"AI角色优化失败: {str(e)}")
            raise
    
    async def analyze_worldview(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """AI分析世界观"""
        prompt = ChatPromptTemplate.from_template("""
        你是一个专业的世界观分析师。请对以下世界观设定进行深度分析。

        小说信息：
        - 标题：{novel_title}
        - 类型：{novel_genre}
        - 世界观：{worldview}
        
        现有设定：
        {existing_settings}
        
        请从以下维度进行分析：
        
        1. 一致性分析
        - 设定内部逻辑一致性
        - 不同设定间的协调性
        - 潜在的逻辑冲突
        
        2. 完整性分析
        - 世界观覆盖范围
        - 缺失的重要设定
        - 需要补充的细节
        
        3. 复杂度分析
        - 设定复杂程度评估
        - 读者理解难度
        - 创作实施难度
        
        4. 独特性分析
        - 创新点识别
        - 与同类作品对比
        - 特色优势分析
        
        5. 实用性分析
        - 对情节发展的支撑
        - 对角色塑造的帮助
        - 对冲突设计的价值
        
        请以JSON格式返回分析结果：
        {{
            "consistency_analysis": {{
                "internal_logic_score": 评分(1-10),
                "coordination_score": 评分(1-10),
                "conflicts": ["冲突1", "冲突2"],
                "consistency_suggestions": ["建议1", "建议2"]
            }},
            "completeness_analysis": {{
                "coverage_score": 评分(1-10),
                "missing_elements": ["缺失1", "缺失2"],
                "detail_gaps": ["细节缺口1", "细节缺口2"],
                "completion_suggestions": ["补充建议1", "补充建议2"]
            }},
            "complexity_analysis": {{
                "complexity_level": "简单/中等/复杂",
                "reader_difficulty": 评分(1-10),
                "creation_difficulty": 评分(1-10),
                "complexity_suggestions": ["建议1", "建议2"]
            }},
            "uniqueness_analysis": {{
                "innovation_score": 评分(1-10),
                "unique_elements": ["特色1", "特色2"],
                "competitive_advantages": ["优势1", "优势2"],
                "differentiation_suggestions": ["建议1", "建议2"]
            }},
            "practicality_analysis": {{
                "plot_support_score": 评分(1-10),
                "character_support_score": 评分(1-10),
                "conflict_value_score": 评分(1-10),
                "practical_suggestions": ["建议1", "建议2"]
            }},
            "overall_assessment": {{
                "total_score": 评分(1-10),
                "strengths": ["优势1", "优势2"],
                "weaknesses": ["弱点1", "弱点2"],
                "priority_improvements": ["优先改进1", "优先改进2"]
            }}
        }}
        """)
        
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.3,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
            )
            
            chain = prompt | llm
            response = await chain.ainvoke(context)
            
            # 解析JSON响应
            analysis_result = json.loads(response.content)
            analysis_result['analysis_timestamp'] = datetime.utcnow().isoformat()
            
            logger.info(f"AI世界观分析完成: {context.get('novel_title', 'Unknown')}")
            return analysis_result
            
        except Exception as e:
            logger.error(f"AI世界观分析失败: {str(e)}")
            raise
    
    async def optimize_worldview(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """AI优化世界观"""
        prompt = ChatPromptTemplate.from_template("""
        你是一个专业的世界观设计师。请根据分析结果优化世界观设定。

        当前世界观：
        {worldview}
        
        分析结果：
        {analysis_result}
        
        优化目标：
        {optimization_goals}
        
        请提供以下优化建议：
        
        1. 一致性优化
        - 解决逻辑冲突的方案
        - 统一设定标准
        - 建立一致性规则
        
        2. 完整性优化
        - 补充缺失设定
        - 丰富细节描述
        - 扩展覆盖范围
        
        3. 实用性优化
        - 增强情节支撑
        - 优化角色背景
        - 强化冲突基础
        
        4. 独特性优化
        - 突出创新元素
        - 强化特色优势
        - 提升差异化
        
        请以JSON格式返回优化建议：
        {{
            "consistency_optimizations": {{
                "conflict_resolutions": [
                    {{"conflict": "冲突描述", "solution": "解决方案", "implementation": "实施步骤"}}
                ],
                "unification_rules": ["规则1", "规则2"],
                "standard_guidelines": ["指导原则1", "指导原则2"]
            }},
            "completeness_optimizations": {{
                "new_settings": [
                    {{"category": "分类", "name": "名称", "description": "描述", "importance": "重要性"}}
                ],
                "detail_enhancements": [
                    {{"target": "目标设定", "enhancements": ["增强1", "增强2"]}}
                ],
                "expansion_areas": ["扩展领域1", "扩展领域2"]
            }},
            "practicality_optimizations": {{
                "plot_enhancements": ["情节增强1", "情节增强2"],
                "character_background_improvements": ["背景改进1", "背景改进2"],
                "conflict_foundations": ["冲突基础1", "冲突基础2"]
            }},
            "uniqueness_optimizations": {{
                "innovation_highlights": ["创新亮点1", "创新亮点2"],
                "advantage_amplifications": ["优势放大1", "优势放大2"],
                "differentiation_strategies": ["差异化策略1", "差异化策略2"]
            }},
            "implementation_plan": {{
                "phase_1": ["第一阶段任务1", "第一阶段任务2"],
                "phase_2": ["第二阶段任务1", "第二阶段任务2"],
                "phase_3": ["第三阶段任务1", "第三阶段任务2"]
            }},
            "success_metrics": {{
                "consistency_targets": ["一致性目标1", "一致性目标2"],
                "completeness_targets": ["完整性目标1", "完整性目标2"],
                "quality_indicators": ["质量指标1", "质量指标2"]
            }}
        }}
        """)
        
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.5,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
            )
            
            chain = prompt | llm
            response = await chain.ainvoke(context)
            
            # 解析JSON响应
            optimization_result = json.loads(response.content)
            
            logger.info(f"AI世界观优化完成: {context.get('novel_title', 'Unknown')}")
            return optimization_result
            
        except Exception as e:
            logger.error(f"AI世界观优化失败: {str(e)}")
            raise
    
    async def generate_worldview_setting(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """AI生成世界观设定"""
        prompt = ChatPromptTemplate.from_template("""
        你是一个专业的世界观设计师。根据要求生成具体的世界观设定。

        小说信息：
        - 标题：{novel_title}
        - 类型：{novel_genre}
        - 现有世界观：{existing_worldview}
        
        设定要求：
        - 分类：{category}
        - 具体需求：{requirements}
        
        现有相关设定：
        {related_settings}
        
        请生成一个详细的世界观设定，包含：
        1. 设定名称
        2. 详细描述
        3. 运作机制
        4. 相关规则
        5. 对故事的影响
        6. 与其他设定的关联
        
        要求：
        - 与现有世界观保持一致
        - 逻辑自洽，合理可信
        - 有助于情节发展
        - 具有独特性和吸引力
        
        请以JSON格式返回：
        {{
            "name": "设定名称",
            "category": "设定分类",
            "description": "详细描述（200-500字）",
            "mechanism": "运作机制说明",
            "rules": ["规则1", "规则2", "规则3"],
            "story_impact": "对故事的影响",
            "related_connections": ["与设定A的关联", "与设定B的关联"],
            "consistency_rules": ["一致性规则1", "一致性规则2"],
            "importance_level": "重要性级别（high/medium/low）",
            "implementation_suggestions": ["实施建议1", "实施建议2"]
        }}
        """)
        
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.7,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
            )
            
            chain = prompt | llm
            response = await chain.ainvoke(context)
            
            # 解析JSON响应
            setting_data = json.loads(response.content)
            
            logger.info(f"AI生成世界观设定: {setting_data.get('name', 'Unknown')}")
            return setting_data
            
        except Exception as e:
            logger.error(f"AI生成世界观设定失败: {str(e)}")
            raise
    
    async def analyze_plot_structure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """AI分析情节结构"""
        prompt = ChatPromptTemplate.from_template("""
        你是一个专业的情节分析师。请分析小说的情节结构。

        小说信息：
        - 标题：{novel_title}
        - 类型：{novel_genre}
        - 章节数：{chapter_count}
        
        情节元素：
        {plot_elements}
        
        章节概要：
        {chapter_summaries}
        
        请从以下维度分析情节结构：
        
        1. 结构完整性
        - 起承转合是否完整
        - 情节发展是否合理
        - 高潮设置是否恰当
        
        2. 节奏控制
        - 情节推进速度
        - 紧张感营造
        - 缓急交替安排
        
        3. 冲突设计
        - 主要冲突识别
        - 次要冲突分析
        - 冲突解决方式
        
        4. 情节连贯性
        - 前后呼应关系
        - 伏笔铺垫效果
        - 逻辑连接强度
        
        请以JSON格式返回分析结果。
        """)
        
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.3,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
            )
            
            chain = prompt | llm
            response = await chain.ainvoke(context)
            
            analysis_result = json.loads(response.content)
            analysis_result['analysis_timestamp'] = datetime.utcnow().isoformat()
            
            logger.info(f"AI情节结构分析完成: {context.get('novel_title', 'Unknown')}")
            return analysis_result
            
        except Exception as e:
            logger.error(f"AI情节结构分析失败: {str(e)}")
            raise
    
    async def optimize_novel_comprehensive(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """AI全面优化小说"""
        prompt = ChatPromptTemplate.from_template("""
        你是一个资深的小说编辑和创作指导。请对小说进行全面优化。

        小说信息：
        - 标题：{novel_title}
        - 类型：{novel_genre}
        - 当前状态：{current_status}
        
        分析结果：
        {analysis_results}
        
        优化目标：
        {optimization_goals}
        
        请提供系统性的优化方案，包括：
        
        1. 整体结构优化
        2. 角色发展优化
        3. 情节推进优化
        4. 世界观完善
        5. 文风统一
        6. 读者体验提升
        
        请以JSON格式返回详细的优化计划。
        """)
        
        try:
            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL_COMPLEX,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_API_BASE,
                temperature=0.4,
                max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=settings.LLM_MAX_RETRIES,
            )
            
            chain = prompt | llm
            response = await chain.ainvoke(context)
            
            optimization_result = json.loads(response.content)
            optimization_result['optimization_timestamp'] = datetime.utcnow().isoformat()
            
            logger.info(f"AI全面优化完成: {context.get('novel_title', 'Unknown')}")
            return optimization_result
            
        except Exception as e:
            logger.error(f"AI全面优化失败: {str(e)}")
            raise


# 创建全局实例
agent_service = AgentService()
