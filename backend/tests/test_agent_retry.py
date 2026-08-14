"""多 Agent 重试状态与追踪标识测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_service import (
    AgentService,
    _build_consistency_checks,
    _build_final_consistency_status,
)
from app.models.schemas import GenerationRequest


def _initial_state():
    return {
        "novel_id": 1,
        "prompt": "测试剧情",
        "chapter": 1,
        "current_day": 1,
        "target_length": 500,
        "worldview_output": "",
        "character_output": "",
        "plot_output": "",
        "worldview_context": [],
        "character_context": [],
        "consistency_result": {},
        "retry_count": 0,
        "workflow_steps": [],
    }


def test_response_omits_skipped_consistency_layers_instead_of_marking_them_valid():
    """布尔结果无法表达未执行，因此跳过层不应伪造成通过。"""
    checks = _build_consistency_checks(
        {
            "layer_results": {
                "rule_engine": {
                    "status": "completed",
                    "is_valid": True,
                    "violations": [],
                },
                "knowledge_graph": {
                    "status": "skipped",
                    "is_valid": None,
                    "reason": "Neo4j 未启用",
                    "violations": [],
                },
                "timeline": {
                    "status": "completed",
                    "is_valid": True,
                },
                "emotion_state": {
                    "status": "skipped",
                    "is_valid": None,
                },
            }
        }
    )

    assert [check.check_type.value for check in checks] == [
        "rule_engine",
        "timeline",
    ]
    assert all(check.is_valid is True for check in checks)


def test_final_status_is_incomplete_when_checks_were_skipped_without_conflict():
    """无冲突但检查不完整时，不得返回 passed。"""
    status = _build_final_consistency_status(
        {
            "has_conflict": False,
            "violations": [],
            "is_complete": False,
            "checks_skipped": ["knowledge_graph", "emotion_state"],
        },
        retry_count=0,
    )

    assert status.model_dump() == {
        "status": "incomplete",
        "has_conflict": False,
        "retry_exhausted": False,
        "is_complete": False,
        "checks_skipped": ["knowledge_graph", "emotion_state"],
        "violations": [],
    }


def test_conflict_status_has_priority_but_preserves_incomplete_checks():
    """冲突优先决定终态，同时保留检查不完整信息。"""
    status = _build_final_consistency_status(
        {
            "has_conflict": True,
            "violations": ["时间线冲突"],
            "is_complete": False,
            "checks_skipped": ["knowledge_graph"],
        },
        retry_count=2,
    )

    assert status.status == "conflict_after_retries"
    assert status.has_conflict is True
    assert status.retry_exhausted is True
    assert status.is_complete is False
    assert status.checks_skipped == ["knowledge_graph"]


class ControlledAgentService(AgentService):
    def __init__(self, conflicts):
        self.conflicts = list(conflicts)
        self.plot_calls = 0
        self.workflow = self._build_workflow()

    async def _retrieve_context(self, state):
        return {"worldview_context": [], "character_context": []}

    async def _agent_a_worldview(self, state):
        return {"worldview_output": "世界观"}

    async def _agent_b_character(self, state):
        return {"character_output": "角色"}

    async def _agent_c_plot(self, state):
        self.plot_calls += 1
        return {"plot_output": f"剧情{self.plot_calls}"}

    async def _consistency_check(self, state):
        index = min(self.plot_calls - 1, len(self.conflicts) - 1)
        return {
            "consistency_result": {
                "has_conflict": self.conflicts[index],
                "violations": ["冲突"] if self.conflicts[index] else [],
            }
        }


@pytest.mark.asyncio
async def test_retry_state_is_written_back_and_stops_after_two_retries():
    service = ControlledAgentService([True, True, True])

    result = await service.workflow.ainvoke(_initial_state())

    assert result["retry_count"] == 2
    assert service.plot_calls == 3


@pytest.mark.asyncio
async def test_retry_stops_as_soon_as_consistency_passes():
    service = ControlledAgentService([True, False])

    result = await service.workflow.ainvoke(_initial_state())

    assert result["retry_count"] == 1
    assert service.plot_calls == 2


@pytest.mark.asyncio
async def test_final_conflict_status_is_preserved_in_sync_and_stream_responses():
    """达到重试上限的冲突稿必须保留明确状态，不能伪装成已通过。"""
    request = GenerationRequest(
        novel_id=1,
        prompt="测试剧情",
        chapter=1,
        target_length=500,
    )

    sync_response = await ControlledAgentService([True, True, True]).generate_content(request)
    assert sync_response.retry_count == 2
    assert sync_response.final_consistency.model_dump() == {
        "status": "conflict_after_retries",
        "has_conflict": True,
        "retry_exhausted": True,
        "is_complete": True,
        "checks_skipped": [],
        "violations": ["冲突"],
    }

    stream_events = []
    async for event in ControlledAgentService([True, True, True]).generate_content_stream(request):
        stream_events.append(event)
    final_response = stream_events[-1]["data"]
    assert final_response.retry_count == 2
    assert final_response.final_consistency.status == "conflict_after_retries"
    assert final_response.final_consistency.has_conflict is True


@pytest.mark.asyncio
async def test_retry_trace_ids_are_unique_and_prompt_is_summarized():
    service = AgentService.__new__(AgentService)
    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content="生成剧情")
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain
    service.llm_complex = object()
    state = _initial_state()
    state.update(
        {
            "worldview_output": "环境",
            "character_output": "人物",
            "retry_count": 1,
            "consistency_result": {
                "has_conflict": True,
                "violations": ["时间线冲突"],
            },
        }
    )

    with patch(
        "app.services.agent_service.ChatPromptTemplate.from_messages",
        return_value=prompt_template,
    ):
        result = await service._agent_c_plot(state)

    step = result["workflow_steps"][0]
    assert step["id"] == "agent_c_plot_1"
    assert step["parent_id"] == "consistency_check_0"
    assert "prompt" not in step["input"]
    assert step["input"]["prompt_length"] == len(state["prompt"])


@pytest.mark.asyncio
async def test_consistency_trace_id_contains_retry_number():
    service = AgentService.__new__(AgentService)
    state = _initial_state()
    state.update(
        {
            "plot_output": "剧情",
            "retry_count": 2,
            "workflow_steps": [
                {"id": "consistency_check_0"},
                {"id": "consistency_check_1"},
            ],
        }
    )
    check_result = {
        "has_conflict": False,
        "violations": [],
        "layer_results": {},
    }

    with patch(
        "app.services.agent_service.consistency_service.check_content",
        AsyncMock(return_value=check_result),
    ):
        result = await service._consistency_check(state)

    ids = [item["id"] for item in result["workflow_steps"]]
    assert ids[-1] == "consistency_check_2"
    assert len(ids) == len(set(ids))
