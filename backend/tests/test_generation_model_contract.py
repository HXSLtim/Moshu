"""生成工作流拒绝截断输出，并保留提供方完成元数据。"""

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError
import pytest

from app.api.routes.consistency import ConsistencyCheckRequest
from app.api.routes.generation import ContinueRequest
from app.models.schemas import GenerationRequest
from app.services.agent_service import AgentService
from app.services.model_result import ModelOutputError


@pytest.mark.parametrize("request_type, fields", [
    (GenerationRequest, {"novel_id": 1, "chapter": 3, "prompt": "继续写作"}),
    (ConsistencyCheckRequest, {"novel_id": 1, "chapter": 3, "content": "待检查正文"}),
    (ContinueRequest, {"novel_id": 1, "chapter_id": 3, "current_content": "已有正文"}),
])
def test_story_day_is_unknown_by_default_and_positive_when_explicit(request_type, fields):
    """未指定日期保留未知语义，日期不能为零或负数。"""
    assert request_type(**fields).current_day is None
    assert request_type(**fields, current_day=9).current_day == 9
    for invalid in (0, -1):
        with pytest.raises(ValidationError):
            request_type(**fields, current_day=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("node", ["_agent_a_worldview", "_agent_b_character", "_agent_c_plot"])
@pytest.mark.parametrize("finish_reason", ["length", "stop"])
async def test_generation_nodes_validate_completion_before_emitting_output(node, finish_reason):
    """任一生成节点收到截断响应时，都不能生成 completed 步骤或可采纳正文。"""
    service = AgentService.__new__(AgentService)
    response = AIMessage(
        content="候选内容",
        response_metadata={"finish_reason": finish_reason, "model_name": "实际返回模型"},
        usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
    )
    service.llm_simple = service.llm_complex = RunnableLambda(lambda _: response)
    state = {
        "prompt": "继续写作", "worldview_context": [], "character_context": [],
        "story_bible_context": [], "worldview_output": "环境", "character_output": "人物",
        "target_length": 500, "consistency_result": {}, "retry_count": 0, "workflow_steps": [],
    }
    if finish_reason == "length":
        with pytest.raises(ModelOutputError) as exc:
            await getattr(service, node)(state)
        assert exc.value.code == "truncated"
        assert state["workflow_steps"] == []
    else:
        result = await getattr(service, node)(state)
        metadata = result["workflow_steps"][0]["llm"]
        assert metadata["finish_reason"] == "stop"
        assert metadata["response_model"] == "实际返回模型"
        assert metadata["usage"] == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
