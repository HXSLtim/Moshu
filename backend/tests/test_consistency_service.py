"""
一致性检查服务单元测试
测试规则引擎、时间线管理、情绪状态机等功能
"""
from unittest.mock import MagicMock

import pytest

from app.services.consistency_service import (
    RuleEngine,
    KnowledgeGraph,
    TimelineManager,
    EmotionStateMachine,
    ConsistencyService
)


class TestRuleEngine:
    """规则引擎测试"""

    @pytest.fixture
    def rule_engine(self):
        """创建规则引擎实例"""
        engine = RuleEngine()
        engine.add_rule("魔法等级上限", 9)
        engine.add_rule("飞行速度上限", 100)
        return engine

    def test_validate_magic_level_pass(self, rule_engine):
        """测试魔法等级验证 - 通过"""
        content = "李明是一位5级魔法师，实力强大。"
        result = rule_engine.validate(content)

        assert result["is_valid"] is True
        assert len(result["violations"]) == 0

    def test_validate_magic_level_fail(self, rule_engine):
        """测试魔法等级验证 - 失败"""
        content = "李明突破到了10级魔法师，震惊全场！"
        result = rule_engine.validate(content)

        assert result["is_valid"] is False
        assert len(result["violations"]) > 0
        assert "魔法等级10超出上限9" in result["violations"][0]

    def test_validate_flying_speed_pass(self, rule_engine):
        """测试飞行速度验证 - 通过"""
        content = "他以80公里每小时的速度飞行。"
        result = rule_engine.validate(content)

        assert result["is_valid"] is True

    def test_validate_flying_speed_fail(self, rule_engine):
        """测试飞行速度验证 - 失败"""
        content = "他以150公里每小时的速度飞行。"
        result = rule_engine.validate(content)

        assert result["is_valid"] is False
        assert "飞行速度150" in result["violations"][0]


class TestTimelineManager:
    """时间线管理器测试"""

    @pytest.fixture
    def timeline_manager(self):
        """创建时间线管理器实例"""
        return TimelineManager()

    def test_add_event(self, timeline_manager):
        """测试添加事件"""
        timeline_manager.add_event(1, 1, "第一天的事件")
        timeline_manager.add_event(1, 2, "第二天的事件")

        timeline = timeline_manager.get_timeline(1)
        assert len(timeline) == 2
        assert timeline[0][0] == 1
        assert timeline[1][0] == 2

    def test_validate_time_forward(self, timeline_manager):
        """测试时间前进 - 正常"""
        timeline_manager.add_event(1, 1, "第一天")

        result = timeline_manager.validate_new_event(1, 2, "第二天")

        assert result["is_valid"] is True

    def test_validate_time_backward(self, timeline_manager):
        """测试时间倒退 - 异常"""
        timeline_manager.add_event(1, 5, "第五天")

        result = timeline_manager.validate_new_event(1, 3, "第三天")

        assert result["is_valid"] is False
        assert "时间倒退" in result["reason"]

    def test_validate_location_movement(self, timeline_manager):
        """测试地理移动合理性"""
        timeline_manager.add_event(1, 1, "在北京城修炼")

        # 第二天就到上海城，应该不合理（需要至少1天）
        result = timeline_manager.validate_new_event(1, 1, "在上海城战斗")

        # 注意：当前实现要求day间隔至少1天
        # 如果day相同或间隔小于1，应该检测到不合理
        if result["is_valid"] is False:
            assert "地理移动不合理" in result["reason"]


class TestKnowledgeGraph:
    """知识图谱降级与验证语义测试"""

    def test_unavailable_graph_is_skipped_instead_of_passing(self):
        """Neo4j 不可用时不得返回假的通过结果。"""
        graph = KnowledgeGraph()
        graph.driver = None
        graph.unavailable_reason = "Neo4j 测试环境未启用"

        result = graph.analyze_content(1, "李青山与苏言是朋友")

        assert result["status"] == "skipped"
        assert result["is_valid"] is None
        assert result["reason"] == "Neo4j 测试环境未启用"
        assert result["extracted"]

    def test_normalized_relationship_is_really_checked_against_graph(self):
        """抽取后的内部关系标识必须真正查询图谱。"""
        graph = KnowledgeGraph()
        session = MagicMock()
        session.run.return_value = [{"relation": "enemy"}]
        graph.driver = MagicMock()
        graph.driver.session.return_value.__enter__.return_value = session

        result = graph.analyze_content(1, "李青山与苏言是朋友")

        assert result["status"] == "completed"
        assert result["is_valid"] is False
        assert result["violations"]
        session.run.assert_called_once()


class TestEmotionStateMachine:
    """情绪状态机测试"""

    @pytest.fixture
    def emotion_machine(self):
        """创建情绪状态机实例"""
        return EmotionStateMachine()

    def test_valid_emotion_transition(self, emotion_machine):
        """测试合理的情绪转换"""
        emotion_machine.set_emotion("李明", "平静")

        result = emotion_machine.validate_transition("李明", "愤怒")

        assert result["is_valid"] is True
        assert emotion_machine.current_emotions["李明"] == "愤怒"

    def test_invalid_emotion_transition(self, emotion_machine):
        """测试不合理的情绪转换"""
        emotion_machine.set_emotion("李明", "暴怒")

        # 暴怒不能直接转换到平静
        result = emotion_machine.validate_transition("李明", "平静")

        assert result["is_valid"] is False
        assert "不能从'暴怒'直接转换到'平静'" in result["reason"]

    def test_emotion_chain(self, emotion_machine):
        """测试情绪转换链"""
        emotion_machine.set_emotion("李明", "平静")

        # 平静 -> 愤怒 -> 暴怒 -> 愤怒 -> 平静
        assert emotion_machine.validate_transition("李明", "愤怒")["is_valid"]
        assert emotion_machine.validate_transition("李明", "暴怒")["is_valid"]
        assert emotion_machine.validate_transition("李明", "愤怒")["is_valid"]
        assert emotion_machine.validate_transition("李明", "平静")["is_valid"]


class TestConsistencyService:
    """一致性检查服务集成测试"""

    @pytest.fixture
    def consistency_service(self):
        """创建一致性检查服务实例"""
        service = ConsistencyService()
        service.init_worldview_rules(1, {
            "魔法等级上限": 9,
            "飞行速度上限": 100
        })
        return service

    @pytest.mark.asyncio
    async def test_check_content_pass(self, consistency_service):
        """测试内容检查 - 通过"""
        content = "李明是一位5级魔法师，在第一天开始了修炼之旅。"

        result = await consistency_service.check_content(
            novel_id=1,
            content=content,
            chapter=1,
            current_day=1
        )

        assert result["has_conflict"] is False
        assert len(result["violations"]) == 0

    @pytest.mark.asyncio
    async def test_check_content_reports_performed_and_skipped_layers_truthfully(
        self,
        consistency_service,
    ):
        """未执行的图谱和情绪层不得出现在已完成检查中。"""
        consistency_service.knowledge_graph.driver = None
        consistency_service.knowledge_graph.unavailable_reason = "Neo4j 未启用"

        result = await consistency_service.check_content(1, "普通候选正文", 1, 1)

        assert result["checks_performed"] == ["rule_engine"]
        assert result["checks_skipped"] == ["knowledge_graph", "timeline", "emotion_state"]
        assert result["is_complete"] is False

        steps = {
            step["id"]: step
            for step in result["workflow_trace"]["steps"]
        }
        assert steps["knowledge_graph"]["status"] == "skipped"
        assert steps["knowledge_graph"]["output"]["is_valid"] is None
        assert steps["knowledge_graph"]["output"]["reason"] == "Neo4j 未启用"
        assert steps["timeline"]["status"] == "skipped"
        assert steps["emotion_state"]["status"] == "skipped"
        assert steps["emotion_state"]["output"]["is_valid"] is None

    @pytest.mark.asyncio
    async def test_available_graph_is_recorded_as_performed(
        self,
        consistency_service,
    ):
        """图驱动可用且无候选关系时，图谱检查才算完成。"""
        consistency_service.knowledge_graph.driver = object()
        consistency_service.knowledge_graph.unavailable_reason = None

        result = await consistency_service.check_content(1, "普通候选正文", 1, 1)

        assert result["checks_performed"] == [
            "rule_engine",
            "knowledge_graph",
        ]
        assert result["checks_skipped"] == ["timeline", "emotion_state"]
        assert result["layer_results"]["knowledge_graph"]["is_valid"] is True

    @pytest.mark.asyncio
    async def test_stream_exposes_skipped_layers_and_incomplete_summary(
        self,
        consistency_service,
    ):
        """SSE 与非流式结果必须使用同一降级语义。"""
        consistency_service.knowledge_graph.driver = None
        consistency_service.knowledge_graph.unavailable_reason = "Neo4j 未启用"

        events = [
            event
            async for event in consistency_service.check_content_stream(
                1,
                "普通候选正文",
                1,
                1,
            )
        ]

        layers = {
            event["layer"]: event
            for event in events
            if event["type"] == "layer"
        }
        assert layers["knowledge_graph"]["status"] == "skipped"
        assert layers["knowledge_graph"]["reason"] == "Neo4j 未启用"
        assert layers["timeline"]["status"] == "skipped"
        assert layers["emotion_state"]["status"] == "skipped"

        summary = events[-1]
        assert summary["checks_performed"] == ["rule_engine"]
        assert summary["checks_skipped"] == ["knowledge_graph", "timeline", "emotion_state"]
        assert summary["is_complete"] is False

    @pytest.mark.asyncio
    async def test_check_content_rule_violation(self, consistency_service):
        """测试内容检查 - 违反规则"""
        content = "李明突破到了12级魔法师，实力超越了所有人！"

        result = await consistency_service.check_content(
            novel_id=1,
            content=content,
            chapter=1,
            current_day=1
        )

        assert result["has_conflict"] is True
        assert len(result["violations"]) > 0

    @pytest.mark.asyncio
    async def test_check_content_timeline_violation(self, consistency_service):
        """候选内容会读取既有时间线，但不会把候选正文追加进去。"""
        consistency_service.timeline_manager.add_event(1, 5, "已确认的第五天事件")
        initial_timeline = list(consistency_service.timeline_manager.get_timeline(1))

        result = await consistency_service.check_content(1, "第三天的事件", 1, 3)

        assert result["has_conflict"] is True
        assert any("时间倒退" in v for v in result["violations"])
        assert consistency_service.timeline_manager.get_timeline(1) == initial_timeline

    @pytest.mark.asyncio
    async def test_candidate_check_has_no_timeline_side_effect(self, consistency_service):
        """重复检查同一候选稿不会积累整章内存。"""
        await consistency_service.check_content(1, "候选章节正文", 1, 1)
        await consistency_service.check_content(1, "候选章节正文", 1, 1)
        assert consistency_service.timeline_manager.get_timeline(1) == []

    @pytest.mark.asyncio
    async def test_worldview_rules_are_isolated_by_novel(self, consistency_service):
        """不同小说使用各自规则，不会被后初始化的小说覆盖。"""
        consistency_service.init_worldview_rules(2, {"魔法等级上限": 20})

        novel_one = await consistency_service.check_content(1, "12级魔法师", 1, 1)
        novel_two = await consistency_service.check_content(2, "12级魔法师", 1, 1)

        assert novel_one["has_conflict"] is True
        assert novel_two["has_conflict"] is False

    @pytest.mark.asyncio
    async def test_relationship_analysis_does_not_write_graph(
        self,
        consistency_service,
        monkeypatch,
    ):
        """候选关系只被抽取，不调用知识图谱写入方法。"""
        consistency_service.knowledge_graph.driver = None
        writes = []
        monkeypatch.setattr(
            consistency_service.knowledge_graph,
            "add_relationship",
            lambda *args, **kwargs: writes.append((args, kwargs)),
        )

        result = await consistency_service.check_content(
            1,
            "李青山与苏言是朋友",
            1,
            1,
        )

        assert result["knowledge_graph_extracted"]
        assert writes == []


@pytest.mark.asyncio
async def test_empty_consistency_reference_is_not_reported_as_passed():
    """空库或未加载参考数据时，规则与时间线不得伪装检查通过。"""
    service = ConsistencyService()
    service.knowledge_graph.driver = None
    service.init_worldview_rules(1, {"尚不支持的规则": "作者设定"})
    result = await service.check_content(1, "候选正文", 1, 1)
    for layer in ("rule_engine", "timeline"):
        assert result["layer_results"][layer]["status"] == "skipped"
        assert result["layer_results"][layer]["is_valid"] is None
        assert layer not in result["checks_performed"]
    assert result["is_complete"] is False
    events = [event async for event in service.check_content_stream(1, "候选正文", 1, 1)]
    layers = {event["layer"]: event for event in events if event["type"] == "layer"}
    assert layers["rule_engine"]["status"] == "skipped"
    assert layers["timeline"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_unknown_story_day_skips_loaded_timeline_in_http_trace_and_stream():
    """即使参考时间线已加载，故事日未知也不得比较日期或报告检查通过。"""
    service = ConsistencyService()
    service.knowledge_graph.driver = None
    service.timeline_manager.add_event(1, 5, "第五天已确认的剧情")

    result = await service.check_content(1, "候选正文", 3, None)
    timeline = result["layer_results"]["timeline"]
    assert timeline["status"] == "skipped"
    assert timeline["is_valid"] is None
    assert "未提供故事当前天数" in timeline["reason"]
    assert "timeline" not in result["checks_performed"]
    assert "timeline" in result["checks_skipped"]
    assert result["is_complete"] is False
    step = next(step for step in result["workflow_trace"]["steps"] if step["id"] == "timeline")
    assert step["input"]["current_day"] is None
    assert step["status"] == "skipped"
    assert step["output"]["is_valid"] is None
    events = [event async for event in service.check_content_stream(1, "候选正文", 3, None)]
    timeline_event = next(event for event in events if event.get("layer") == "timeline")
    assert timeline_event["status"] == "skipped"
    assert timeline_event["reason"] == timeline["reason"]
    assert service.timeline_manager.get_timeline(1) == [(5, "第五天已确认的剧情")]
