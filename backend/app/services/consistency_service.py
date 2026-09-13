"""一致性检查服务

实现四层防护机制：规则引擎、知识图谱、时间线管理、情绪状态机，
并提供 Agent 工作流追踪信息，便于前端可视化展示检查流程和数据流。
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import re
from neo4j import GraphDatabase
from app.core.config import settings
from loguru import logger

from app.models.workflow_schemas import AgentWorkflowStep, AgentWorkflowTrace


# ========== 规则引擎 ==========

class RuleEngine:
    """规则引擎：验证硬规则"""

    def __init__(self):
        self.rules_by_novel: Dict[int, Dict[str, Any]] = {}

    def add_rule(self, name: str, value: Any, novel_id: int = 0):
        """为指定小说添加规则；0用于独立规则引擎的默认作用域。"""
        self.rules_by_novel.setdefault(novel_id, {})[name] = value

    def set_rules(self, novel_id: int, rules: Dict[str, Any]) -> None:
        """原子替换小说规则，防止旧规则残留。"""
        self.rules_by_novel[novel_id] = dict(rules)

    def validate(self, content: str, novel_id: int = 0) -> Dict[str, Any]:
        """
        验证内容是否违反硬规则

        Args:
            content: 待验证内容

        Returns:
            验证结果
        """
        violations = []
        rules = self.rules_by_novel.get(novel_id, {})

        # 检查魔法等级
        if "魔法等级上限" in rules:
            matches = re.findall(r"(\d+)级魔法师", content)
            for match in matches:
                level = int(match)
                if level > rules["魔法等级上限"]:
                    violations.append(
                        f"魔法等级{level}超出上限{rules['魔法等级上限']}"
                    )

        # 检查飞行速度
        if "飞行速度上限" in rules:
            matches = re.findall(r"以(\d+)(?:公里|千米)(?:每|\/)?小时", content)
            for match in matches:
                speed = int(match)
                if speed > rules["飞行速度上限"]:
                    violations.append(
                        f"飞行速度{speed}km/h超出上限{rules['飞行速度上限']}km/h"
                    )

        return {
            "is_valid": len(violations) == 0,
            "violations": violations
        }


# ========== 知识图谱 ==========

class KnowledgeGraph:
    """知识图谱：验证角色关系和地理位置

    当前主要支持：
    - 解析文本里的简单角色关系句式（如“李青山是苏言的老师”“李青山与苏言是朋友”）
    - 将关系归一化为 friend/ally/enemy/mentor/lover 等语义并写入 Neo4j
    - 检测与已有关系的冲突（例如 friend vs enemy）
    """

    # 关系同义词归一化表
    RELATION_SYNONYMS = {
        "朋友": "friend",
        "好友": "friend",
        "挚友": "friend",
        "盟友": "ally",
        "同盟": "ally",
        "敌人": "enemy",
        "仇人": "enemy",
        "宿敌": "enemy",
        "老师": "mentor",
        "师父": "mentor",
        "导师": "mentor",
        "徒弟": "disciple",
        "学生": "disciple",
        "恋人": "lover",
        "爱人": "lover",
        "伴侣": "lover",
    }

    # 关系的反向映射
    RELATION_INVERSE = {
        "mentor": "disciple",
        "disciple": "mentor",
        "lover": "lover",
        "friend": "friend",
        "ally": "ally",
        "enemy": "enemy",
    }

    # 被视为互斥的关系集合
    RELATION_CONFLICTS = [
        {"friend", "enemy"},
        {"ally", "enemy"},
        {"lover", "enemy"},
    ]

    def __init__(self):
        self.driver = None
        self.unavailable_reason: Optional[str] = None
        if not settings.NEO4J_ENABLED:
            self.unavailable_reason = "Neo4j 未启用，仅执行本地关系抽取，未执行知识图谱冲突验证"
            logger.warning(self.unavailable_reason)
            return

        try:
            self.driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                connection_timeout=2,
            )
            self.driver.verify_connectivity()
            logger.info("Neo4j 连接验证成功")
        except Exception as e:
            self.unavailable_reason = f"Neo4j 连接失败，未执行知识图谱冲突验证：{e}"
            logger.warning(self.unavailable_reason)
            if self.driver:
                self.driver.close()
            self.driver = None

    def _normalize_relation(self, relation: Optional[str]) -> Optional[str]:
        """将自然语言关系归一化为内部标识，如“朋友”->"friend""" 
        if not relation:
            return None
        normalized = relation.strip()
        if normalized in self.RELATION_SYNONYMS.values():
            return normalized
        return self.RELATION_SYNONYMS.get(normalized)

    def _is_conflict(self, relation_a: str, relation_b: str) -> bool:
        """判断两个关系是否属于互斥关系"""
        if relation_a == relation_b:
            return False
        for conflict in self.RELATION_CONFLICTS:
            if relation_a in conflict and relation_b in conflict:
                return True
        return False

    def _extract_relationships(self, content: str) -> List[Dict[str, str]]:
        """从文本中抽取简单角色关系

        支持的句式示例：
        - "李青山是苏言的老师"
        - "李青山与苏言是朋友"
        """
        if not content:
            return []

        relationships: List[Dict[str, str]] = []

        # 句式1：A是B的X
        pattern_possessive = re.compile(
            r"(?P<a>[\u4e00-\u9fa5A-Za-z]{2,})是(?P<b>[\u4e00-\u9fa5A-Za-z]{2,})的(?P<relation>[\u4e00-\u9fa5A-Za-z]{1,4})"
        )

        # 句式2：A与B是X
        pattern_pair = re.compile(
            r"(?P<a>[\u4e00-\u9fa5A-Za-z]{2,})与(?P<b>[\u4e00-\u9fa5A-Za-z]{2,})是(?P<relation>[\u4e00-\u9fa5A-Za-z]{1,4})"
        )

        for match in pattern_possessive.finditer(content):
            relation = self._normalize_relation(match.group("relation"))
            if not relation:
                continue
            relationships.append(
                {
                    "source": match.group("a"),
                    "target": match.group("b"),
                    "relation": relation,
                }
            )

        for match in pattern_pair.finditer(content):
            relation = self._normalize_relation(match.group("relation"))
            if not relation:
                continue
            relationships.append(
                {
                    "source": match.group("a"),
                    "target": match.group("b"),
                    "relation": relation,
                }
            )

        return relationships

    def _upsert_relationship(self, novel_id: int, char_a: str, char_b: str, relation: str) -> None:
        """向 Neo4j 中写入或更新角色关系（带 novel_id 作用域）"""
        if not self.driver:
            return

        with self.driver.session() as session:
            session.run(
                "MERGE (a:Character {name: $name_a, novel_id: $novel_id}) "
                "MERGE (b:Character {name: $name_b, novel_id: $novel_id}) "
                "MERGE (a)-[r:RELATION {novel_id: $novel_id}]->(b) "
                "SET r.type = $relation",
                name_a=char_a,
                name_b=char_b,
                relation=relation,
                novel_id=novel_id,
            )

    def add_relationship(self, novel_id: int, char_a: str, char_b: str, relation: str) -> None:
        """添加角色关系（会自动写入正向与反向关系）"""
        normalized = self._normalize_relation(relation)
        if not normalized or not self.driver:
            return

        self._upsert_relationship(novel_id, char_a, char_b, normalized)

        inverse = self.RELATION_INVERSE.get(normalized)
        if inverse:
            self._upsert_relationship(novel_id, char_b, char_a, inverse)

    def validate_relationship(self, novel_id: int, char_a: str, char_b: str, new_relation: str) -> Dict[str, Any]:
        """验证新关系是否与已有关系冲突"""
        normalized = self._normalize_relation(new_relation)
        if not normalized:
            return {"is_valid": True}
        if not self.driver:
            return {
                "status": "skipped",
                "is_valid": None,
                "reason": self.unavailable_reason or "Neo4j 不可用，未执行知识图谱冲突验证",
            }

        with self.driver.session() as session:
            result = session.run(
                "MATCH (a:Character {name: $name_a, novel_id: $novel_id})-"
                "[r:RELATION {novel_id: $novel_id}]->(b:Character {name: $name_b, novel_id: $novel_id}) "
                "RETURN r.type AS relation",
                name_a=char_a,
                name_b=char_b,
                novel_id=novel_id,
            )
            existing_relations = [record["relation"] for record in result]

        for existing in existing_relations:
            if self._is_conflict(existing, normalized):
                return {
                    "status": "completed",
                    "is_valid": False,
                    "reason": f"{char_a}和{char_b}已有关系{existing_relations}，与新关系'{new_relation}'矛盾",
                }

        return {"status": "completed", "is_valid": True, "normalized": normalized}

    def analyze_content(self, novel_id: int, content: str) -> Dict[str, Any]:
        """只读分析候选内容，不把候选关系写入知识图谱。"""
        relationships = self._extract_relationships(content)
        if not self.driver:
            return {
                "status": "skipped",
                "is_valid": None,
                "reason": self.unavailable_reason or "Neo4j 不可用，未执行知识图谱冲突验证",
                "violations": [],
                "extracted": relationships,
            }

        if not relationships:
            return {
                "status": "completed",
                "is_valid": True,
                "violations": [],
                "extracted": [],
            }

        violations: List[str] = []
        extracted: List[Dict[str, str]] = []

        for rel in relationships:
            result = self.validate_relationship(
                novel_id=novel_id,
                char_a=rel["source"],
                char_b=rel["target"],
                new_relation=rel["relation"],
            )
            if not result.get("is_valid", True):
                violations.append(result.get("reason") or "角色关系与既有设定冲突")
                continue

            normalized = result.get("normalized") or rel["relation"]
            extracted.append({**rel, "relation": normalized})

        return {
            "status": "completed",
            "is_valid": not violations,
            "violations": violations,
            "extracted": extracted,
        }

    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()


# ========== 时间线管理器 ==========

class TimelineManager:
    """时间线管理器：验证时间一致性"""

    def __init__(self):
        # 存储每个小说的事件时间线
        self.timelines: Dict[int, List[tuple]] = {}

    def add_event(self, novel_id: int, day: int, event: str):
        """添加事件到时间线"""
        if novel_id not in self.timelines:
            self.timelines[novel_id] = []

        self.timelines[novel_id].append((day, event))
        self.timelines[novel_id].sort(key=lambda x: x[0])

    def validate_new_event(
        self,
        novel_id: int,
        day: Optional[int],
        event: str
    ) -> Dict[str, Any]:
        """
        验证新事件是否违反时间线

        Args:
            novel_id: 小说ID
            day: 事件发生天数
            event: 事件描述

        Returns:
            验证结果
        """
        if day is None:
            return {"status": "skipped", "is_valid": None, "reason": "未提供故事当前天数，无法验证按日时间顺序"}
        if novel_id not in self.timelines or not self.timelines[novel_id]:
            return {"status": "skipped", "is_valid": None, "reason": "没有加载已确认的剧情时间线"}

        last_day, last_event = self.timelines[novel_id][-1]

        # 检查1：新事件不能早于最后事件
        if day < last_day:
            return {
                "is_valid": False,
                "reason": f"时间倒退：新事件在第{day}天，但最新事件在第{last_day}天"
            }

        # 检查2：地理位置移动是否合理（简化检查）
        # 注意：同一天内可以在不同地点发生事件（如从城市出发到郊外），只要时间间隔足够即可
        cities = re.findall(r"([A-Za-z\u4e00-\u9fa5]{2,}(?:城|镇|村|国))", event)
        last_cities = re.findall(r"([A-Za-z\u4e00-\u9fa5]{2,}(?:城|镇|村|国))", last_event)

        if cities and last_cities:
            # 如果位置改变，检查时间间隔是否足够
            # 一般来说，同一天内的位置改变是合理的（如从城市到郊外）
            # 只有当位置改变且时间间隔为0时才需要检查是否合理
            if cities[0] != last_cities[0] and day == last_day:
                # 同一天内位置改变，需要检查是否在同一个事件中描述
                # 这种情况下，应该允许（因为可能是同一个事件中的多个地点）
                # 所以这里不做限制
                pass

        return {"is_valid": True}

    def get_timeline(self, novel_id: int) -> List[tuple]:
        """获取小说的时间线"""
        return self.timelines.get(novel_id, [])


# ========== 情绪状态机 ==========

class EmotionStateMachine:
    """情绪状态机：验证角色情绪转换"""

    def __init__(self):
        # 定义允许的情绪转换
        self.transitions = {
            "平静": ["高兴", "悲伤", "愤怒", "惊讶"],
            "高兴": ["平静", "兴奋", "惊讶"],
            "悲伤": ["平静", "绝望", "愤怒"],
            "愤怒": ["平静", "暴怒", "悲伤"],
            "暴怒": ["愤怒", "悲伤"],  # 不能直接平静
            "兴奋": ["高兴", "平静"],
            "绝望": ["悲伤", "平静"],
            "惊讶": ["平静", "高兴", "恐惧"],
            "恐惧": ["平静", "惊讶", "绝望"]
        }

        # 存储每个角色的当前情绪
        self.current_emotions: Dict[str, str] = {}

    def set_emotion(self, character: str, emotion: str):
        """设置角色情绪"""
        self.current_emotions[character] = emotion

    def validate_transition(
        self,
        character: str,
        new_emotion: str
    ) -> Dict[str, Any]:
        """
        验证情绪转换是否合理

        Args:
            character: 角色名
            new_emotion: 新情绪

        Returns:
            验证结果
        """
        current = self.current_emotions.get(character, "平静")

        if new_emotion in self.transitions.get(current, []):
            self.current_emotions[character] = new_emotion
            return {"is_valid": True}
        else:
            return {
                "is_valid": False,
                "reason": f"{character}的情绪不能从'{current}'直接转换到'{new_emotion}'"
            }


# ========== 一致性检查服务 ==========

class ConsistencyService:
    """一致性检查服务：整合四层防护机制"""

    def __init__(self):
        self.rule_engine = RuleEngine()
        self.knowledge_graph = KnowledgeGraph()
        self.timeline_manager = TimelineManager()
        self.emotion_machine = EmotionStateMachine()

    def init_worldview_rules(self, novel_id: int, rules: Dict[str, Any]):
        """初始化小说的世界观规则"""
        self.rule_engine.set_rules(novel_id, rules)
        logger.info(f"小说{novel_id}初始化了{len(rules)}条世界观规则")

    async def check_content(
        self,
        novel_id: int,
        content: str,
        chapter: int,
        current_day: Optional[int],
        reference: dict | None = None,
    ) -> Dict[str, Any]:
        """
        执行完整的一致性检查

        Args:
            novel_id: 小说ID
            content: 待检查内容
            chapter: 章节号
            current_day: 当前天数

        Returns:
            检查结果
        """
        rule_engine = self.rule_engine
        timeline_manager = self.timeline_manager
        if reference is not None:
            rule_engine = RuleEngine()
            rule_engine.set_rules(novel_id, reference["rules"])
            timeline_manager = TimelineManager()
            for day, description in reference["timeline"]:
                timeline_manager.add_event(novel_id, day, description)
        violations: List[str] = []
        checks_performed: List[str] = []
        checks_skipped: List[str] = []
        steps: List[AgentWorkflowStep] = []

        # 生成本次检查的运行ID
        run_id = f"consistency-{novel_id}-{chapter}-{int(datetime.utcnow().timestamp() * 1000)}"

        # 第1层：规则引擎检查
        rule_start = datetime.utcnow()
        supported_rules = {"魔法等级上限", "飞行速度上限"}
        if supported_rules.intersection(rule_engine.rules_by_novel.get(novel_id, {})):
            rule_result = rule_engine.validate(content, novel_id=novel_id)
            rule_result["status"] = "completed"
            checks_performed.append("rule_engine")
        else:
            rule_result = {"status": "skipped", "is_valid": None, "violations": [],
                           "reason": "没有加载可执行的已确认世界观规则"}
            checks_skipped.append("rule_engine")
        rule_end = datetime.utcnow()
        if rule_result["is_valid"] is False:
            violations.extend(rule_result["violations"])
            logger.warning(f"规则引擎检测到{len(rule_result['violations'])}个违规")

        steps.append(
            AgentWorkflowStep(
                id="rule_engine",
                parent_id=None,
                type="rule_engine",
                agent_name="RuleEngine",
                title="规则引擎检查",
                description="根据预设的世界观硬规则检查文本内容是否违规",
                input={
                    "novel_id": novel_id,
                    "chapter": chapter,
                    "current_day": current_day,
                },
                output={
                    "is_valid": rule_result["is_valid"],
                    "violation_count": len(rule_result["violations"]),
                    "reason": rule_result.get("reason"),
                },
                data_sources={},
                llm={},
                status=rule_result["status"],
                started_at=rule_start,
                finished_at=rule_end,
                duration_ms=int((rule_end - rule_start).total_seconds() * 1000),
            )
        )

        # 第2层：知识图谱检查（角色关系）
        kg_start = datetime.utcnow()
        if reference is None:
            kg_result = self.knowledge_graph.analyze_content(novel_id, content)
        else:
            kg_result = {"status": "skipped", "is_valid": None, "violations": [], "extracted": [],
                         "reason": "关系图谱尚未绑定本轮作者账本来源，未执行关系判定"}
        kg_end = datetime.utcnow()
        kg_status = str(kg_result.get("status", "failed"))
        if kg_status == "completed":
            checks_performed.append("knowledge_graph")
        else:
            checks_skipped.append("knowledge_graph")
        if kg_result.get("violations"):
            violations.extend(kg_result["violations"])
            logger.warning(f"知识图谱检测到{len(kg_result['violations'])}个角色关系冲突")

        steps.append(
            AgentWorkflowStep(
                id="knowledge_graph",
                parent_id="rule_engine",
                type="graph",
                agent_name="KnowledgeGraph",
                title="知识图谱检查角色关系",
                description="从候选文本中抽取角色关系，并只读检测与既有关系的冲突",
                input={
                    "novel_id": novel_id,
                    "chapter": chapter,
                },
                output={
                    "status": kg_status,
                    "is_valid": kg_result.get("is_valid"),
                    "reason": kg_result.get("reason"),
                    "violation_count": len(kg_result.get("violations", [])),
                    "extracted_count": len(kg_result.get("extracted", [])),
                },
                data_sources={
                    "extracted_relationships": kg_result.get("extracted", [])[:10]
                },
                llm={},
                status=kg_status,
                started_at=kg_start,
                finished_at=kg_end,
                duration_ms=int((kg_end - kg_start).total_seconds() * 1000),
            )
        )

        # 第3层：时间线检查
        timeline_start = datetime.utcnow()
        timeline_result = timeline_manager.validate_new_event(novel_id, current_day, content)
        if timeline_result.get("status") == "skipped":
            checks_skipped.append("timeline")
        else:
            timeline_result["status"] = "completed"
            checks_performed.append("timeline")
        timeline_end = datetime.utcnow()
        if timeline_result["is_valid"] is False:
            violations.append(timeline_result["reason"])
            logger.warning(f"时间线检测到违规：{timeline_result['reason']}")

        steps.append(
            AgentWorkflowStep(
                id="timeline",
                parent_id="knowledge_graph",
                type="timeline",
                agent_name="TimelineManager",
                title="时间线检查",
                description="只读验证候选事件的时间顺序和地理移动是否合理",
                input={
                    "novel_id": novel_id,
                    "current_day": current_day,
                },
                output={
                    "is_valid": timeline_result["is_valid"],
                    "reason": timeline_result.get("reason"),
                },
                data_sources={},
                llm={},
                status=timeline_result["status"],
                started_at=timeline_start,
                finished_at=timeline_end,
                duration_ms=int((timeline_end - timeline_start).total_seconds() * 1000),
            )
        )

        # 第4层：情绪状态机检查（暂未实现，必须明确标记为跳过）
        emotion_result = {
            "status": "skipped",
            "is_valid": None,
            "reason": "当前尚未从候选正文抽取角色情绪转换，未执行情绪一致性验证",
        }
        checks_skipped.append("emotion_state")

        steps.append(
            AgentWorkflowStep(
                id="emotion_state",
                parent_id="timeline",
                type="emotion_state",
                agent_name="EmotionStateMachine",
                title="情绪状态机检查（占位）",
                description="预留用于未来的情绪状态机一致性检查，目前暂未实现",
                input={},
                output=emotion_result,
                data_sources={},
                llm={},
                status="skipped",
                started_at=None,
                finished_at=None,
                duration_ms=None,
            )
        )

        # 构建工作流追踪
        workflow_trace = AgentWorkflowTrace(
            run_id=run_id,
            trigger="consistency.check_content",
            novel_id=novel_id,
            chapter_id=chapter,
            user_id=None,
            summary=f"小说{novel_id} 第{chapter}章的一致性检查",
            steps=steps,
        )

        return {
            "reference": reference,
            "has_conflict": len(violations) > 0,
            "violations": violations,
            "checks_performed": checks_performed,
            "checks_skipped": checks_skipped,
            "is_complete": not checks_skipped,
            "knowledge_graph_extracted": kg_result.get("extracted", []),
            # 分层结果，供流式接口和前端可视化使用
            "layer_results": {
                "rule_engine": rule_result,
                "knowledge_graph": kg_result,
                "timeline": timeline_result,
                "emotion_state": emotion_result,
            },
            # 完整工作流追踪信息
            "workflow_trace": workflow_trace.model_dump(),
        }

    async def check_content_stream(
        self,
        novel_id: int,
        content: str,
        chapter: int,
        current_day: Optional[int],
        reference: dict | None = None,
    ):
        """以流式形式执行一致性检查，按步骤产出事件。

        该方法主要用于 SSE 接口，整体检查逻辑与 ``check_content`` 保持一致，
        但会在每一层检查完成后产出一个事件，最后再产出汇总结果。

        Yields:
            dict: 形如 {"type": "layer" | "summary", ...} 的事件字典。
        """

        # 复用非流式检查逻辑，确保结果一致，并在此基础上拆分流式事件
        result = await self.check_content(
            novel_id=novel_id,
            content=content,
            chapter=chapter,
            current_day=current_day,
            **({"reference": reference} if reference is not None else {}),
        )

        layer_results = result.get("layer_results", {})

        # 第1层：规则引擎
        rule_result = layer_results.get("rule_engine", {})
        yield {
            "type": "layer",
            "layer": "rule_engine",
            "status": ("skipped" if rule_result.get("status") == "skipped"
                       else "ok" if rule_result.get("is_valid") else "violation"),
            "reason": rule_result.get("reason"),
            "violations": rule_result.get("violations", []),
        }

        # 第2层：知识图谱
        kg_result = layer_results.get("knowledge_graph", {})
        kg_violations = kg_result.get("violations", [])
        yield {
            "type": "layer",
            "layer": "knowledge_graph",
            "status": (
                "ok" if kg_result.get("status") == "completed" and not kg_violations
                else "violation" if kg_result.get("status") == "completed"
                else kg_result.get("status", "failed")
            ),
            "reason": kg_result.get("reason"),
            "violations": kg_violations,
            "extracted": kg_result.get("extracted", []),
        }

        # 第3层：时间线
        timeline_result = layer_results.get("timeline", {})
        timeline_is_valid = timeline_result.get("is_valid", True)
        yield {
            "type": "layer",
            "layer": "timeline",
            "status": ("skipped" if timeline_result.get("status") == "skipped"
                       else "ok" if timeline_is_valid else "violation"),
            "reason": timeline_result.get("reason"),
            "violations": ([timeline_result.get("reason")] if timeline_is_valid is False else []),
        }

        # 第4层：情绪状态机（当前未执行）
        emotion_result = layer_results.get("emotion_state", {})
        yield {
            "type": "layer",
            "layer": "emotion_state",
            "status": emotion_result.get("status", "skipped"),
            "reason": emotion_result.get("reason"),
            "violations": [],
        }

        # 最终汇总事件，附带workflow_trace，便于前端获取完整工作流
        summary = {
            "type": "summary",
            "has_conflict": result.get("has_conflict", False),
            "violations": result.get("violations", []),
            "checks_performed": result.get("checks_performed", []),
            "checks_skipped": result.get("checks_skipped", []),
            "is_complete": result.get("is_complete", False),
            "knowledge_graph_extracted": result.get("knowledge_graph_extracted", []),
            "workflow_trace": result.get("workflow_trace"),
        }
        yield summary


# 创建全局实例
consistency_service = ConsistencyService()
