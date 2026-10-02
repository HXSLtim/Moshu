"""模型调用前的真实 Prompt 渲染、数据边界与历史范围回归。"""
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.services.review import agents as review_agents
from app.services.generation.workflow import GenerationWorkflow


REVIEW_CASES = [
    ("review_pace_agent", {"score": 80, "pace_type": "medium", "issues": [], "suggestions": [], "details": {}}),
    ("review_quality_agent", {"score": 80, "grammar_score": 80, "logic_score": 80, "description_score": 80, "issues": [], "suggestions": []}),
    ("review_plot_coherence_agent", {"score": 80, "coherence_issues": [], "plot_holes": [], "suggestions": []}),
    ("review_character_consistency_agent", {"score": 80, "inconsistencies": [], "suggestions": []}),
    ("review_style_agent", {"score": 80, "style_type": "现代", "consistency_score": 80, "issues": [], "suggestions": []}),
    ("review_content_safety_agent", {"is_safe": True, "risk_level": "low", "flagged_content": [], "suggestions": []}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("agent_name", "payload"), REVIEW_CASES)
async def test_review_preserves_braces_in_manuscript(monkeypatch, agent_name, payload):
    """正文与前文的花括号、JSON 和孤立括号均作为原文传入，不解析成变量。"""
    manuscript = '主角打开{属性面板}，看到{"灵力": 9}，屏幕最后留下一个{。'
    previous = '上章出现{旧面板}。'
    seen = []

    async def answer(prompt):
        seen.extend(prompt.to_messages())
        return AIMessage(content=json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(review_agents.rag_service, "retrieve_character_info", AsyncMock(return_value=['历史中有{原样设定}']))
    kwargs = dict(llm=RunnableLambda(answer), novel_id=1, chapter_number=2, content=manuscript, workflow_steps=[])
    if agent_name == "review_plot_coherence_agent":
        kwargs["previous_chapters"] = [previous]
    result = await getattr(review_agents, agent_name)(**kwargs)
    assert result == payload
    assert manuscript in seen[-1].content
    if agent_name == "review_plot_coherence_agent":
        assert previous in seen[-1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("chapter_number", [1, 3])
async def test_character_review_never_removes_history_boundary(monkeypatch, chapter_number):
    """首章没有前文章节，不得用 None 开启全书检索；其余章节只读前文。"""
    retrieve = AsyncMock(return_value=["已经发生的人物经历"])
    monkeypatch.setattr(review_agents.rag_service, "retrieve_character_info", retrieve)
    payload = {"score": 80, "inconsistencies": [], "suggestions": []}
    model = RunnableLambda(lambda _: AIMessage(content=json.dumps(payload)))
    await review_agents.review_character_consistency_agent(model, 1, chapter_number, "正文", [])
    if chapter_number == 1:
        retrieve.assert_not_called()
    else:
        assert retrieve.await_args.kwargs["max_chapter"] == chapter_number - 1


@pytest.mark.asyncio
async def test_retry_diagnostics_are_data_not_prompt_variables():
    """检查反馈中的花括号不会令剧情修复轮次在调用模型之前失败。"""
    seen = []

    async def answer(prompt):
        seen.extend(prompt.to_messages())
        return AIMessage(content="已修正的候选正文")

    service = GenerationWorkflow.__new__(GenerationWorkflow)
    service.llm_complex = RunnableLambda(answer)
    violation = '状态{持有物}与设定冲突，原文为{"宝剑": 0}。'
    state = dict(prompt="请继续", worldview_output="环境", character_output="人物", story_bible_context=[],
                 target_length=500, consistency_result={"has_conflict": True, "violations": [violation]},
                 retry_count=1, workflow_steps=[])
    result = await service._agent_c_plot(state)
    assert result["plot_output"] == "已修正的候选正文"
    assert violation in seen[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(('agent_name', 'payload'), REVIEW_CASES)
async def test_review_rejects_valid_json_when_provider_reports_truncation(monkeypatch, agent_name, payload):
    """即使 JSON 语法完整，提供方报告截断也不得产出成功审核分数。"""
    from app.services.model.result import ModelOutputError
    monkeypatch.setattr(review_agents.rag_service, 'retrieve_character_info', AsyncMock(return_value=[]))
    model = RunnableLambda(lambda _: AIMessage(content=json.dumps(payload), response_metadata={'finish_reason': 'length'}))
    steps = []
    kwargs = dict(llm=model, novel_id=1, chapter_number=1, content='正文', workflow_steps=steps)
    if agent_name == 'review_plot_coherence_agent':
        kwargs['previous_chapters'] = []
    with pytest.raises(ModelOutputError):
        await getattr(review_agents, agent_name)(**kwargs)
    assert not any(step['status'] == 'completed' for step in steps)
