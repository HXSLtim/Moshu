"""Story Bible 事实与事件进入生成上下文的回归测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # 注册完整SQLAlchemy模型
from app.crud.story_bible import (
    get_active_facts_for_generation,
    get_events_for_generation,
)
from app.db.base import Base
from app.models.story_bible import StoryEvent, StoryFact
from app.models.novel import Novel
from app.services.context.builder import ContextPack
from app.services.generation.workflow import AgentService
from app.services.context.budget import (
    MAX_STORY_BIBLE_CONTEXT_CHARS,
    build_story_bible_context,
)


@pytest.fixture
def story_bible_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    db.add(Novel(id=1, user_id=7, title="测试小说", rag_lifecycle_id="story-life"))
    db.commit()
    db.add_all(
        [
            StoryFact(
                id=1,
                novel_id=1, novel_lifecycle_id="story-life",
                subject="林夏",
                attribute="身份",
                value="青州城守将",
                status="active",
            ),
            StoryFact(
                id=2,
                novel_id=1, novel_lifecycle_id="story-life",
                subject="青州城",
                attribute="戒严原因",
                value="追查玉佩失窃",
                status="active",
                chapter_established=3,
            ),
            StoryFact(
                id=3,
                novel_id=1, novel_lifecycle_id="story-life",
                subject="林夏",
                attribute="位置",
                value="云梦泽",
                status="active",
                chapter_established=5,
            ),
            StoryFact(
                id=4,
                novel_id=1, novel_lifecycle_id="story-life",
                subject="旧设定",
                attribute="身份",
                value="平民",
                status="retired",
                chapter_established=1,
            ),
            StoryEvent(
                id=1,
                novel_id=1,
                title="初入青州",
                description="主角进入青州城，发现城门戒严。",
                story_day=2,
                chapter=2,
                status="occurred",
            ),
            StoryEvent(
                id=2,
                novel_id=1,
                title="未来事件",
                description="不应在第 3 章生成时剧透。",
                story_day=4,
                chapter=4,
                status="planned",
            ),
            StoryEvent(
                id=3,
                novel_id=1,
                title="收到传信",
                description="无章节定位，但已在当前故事日发生。",
                story_day=3,
                chapter=None,
                status="occurred",
            ),
        ]
    )
    db.commit()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_generation_queries_only_include_active_facts_before_target_chapter(
    story_bible_db,
):
    """越界章节事实、退役事实不得进入生成上下文。"""
    facts = get_active_facts_for_generation(
        story_bible_db,
        novel_id=1,
        max_chapter=3,
    )

    assert [fact.id for fact in facts] == [1, 2]
    assert all(fact.status == "active" for fact in facts)


def test_generation_queries_exclude_future_events_and_keep_recent_first(
    story_bible_db,
):
    """事件按目标章节与故事日过滤，查询结果供格式化器反转为时间顺序。"""
    events = get_events_for_generation(
        story_bible_db,
        novel_id=1,
        max_chapter=3,
        current_day=3,
    )

    assert [event.id for event in events] == [3, 1]


def test_historical_generation_uses_fact_valid_at_target_chapter(story_bible_db):
    """回写旧章仍可读取当时持有的物品，失效章及之后不能继续使用。"""
    story_bible_db.add(StoryFact(
        id=10, novel_id=1, subject="主角", attribute="持有物", value="青霜剑",
        status="retired", chapter_established=3, retired_chapter=12,
    ))
    story_bible_db.commit()
    for chapter, expected in [(2, False), (3, True), (11, True), (12, False), (20, False), (None, False)]:
        facts = get_active_facts_for_generation(story_bible_db, 1, max_chapter=chapter)
        assert (10 in [fact.id for fact in facts]) is expected


def test_planned_events_cannot_enter_confirmed_generation_context(story_bible_db):
    """即使计划的章号已到，也不能把未发生事件当成既定剧情。"""
    story_bible_db.add(StoryEvent(
        id=10, novel_id=1, title="计划交出宝剑", description="尚未发生的转交",
        chapter=1, story_day=1, status="planned",
    ))
    story_bible_db.commit()
    events = get_events_for_generation(story_bible_db, 1, max_chapter=3, current_day=3)
    assert 10 not in [event.id for event in events]
    # 格式化边界也拒绝未确认事件，避免其他调用方误传。
    assert "计划交出宝剑" not in "\n".join(build_story_bible_context([], [story_bible_db.get(StoryEvent, 10)]))


def test_story_bible_context_formats_facts_and_events_within_budget():
    """事实与事件合并成行，注入前仍受统一字符预算约束。"""
    facts = [
        SimpleNamespace(
            subject="林夏",
            attribute="身份",
            value="青州城守将",
            description=None,
            chapter_established=1,
        )
    ]
    events = [
        SimpleNamespace(
            title="初入青州",
            description="主角进入青州城。",
            story_day=2,
            chapter=2,
            foreshadowing="城卫认得主角的玉佩",
        )
    ]

    context = build_story_bible_context(facts, events)

    joined = "\n".join(context)
    assert len(joined) <= MAX_STORY_BIBLE_CONTEXT_CHARS
    assert "青州城守将" in joined
    assert "初入青州" in joined
    assert "伏笔：城卫认得主角的玉佩" in joined


def test_story_bible_context_compacts_oversized_inputs():
    """大量长事实与事件进入预算前被裁剪，不会把完整长文塞给模型。"""
    facts = [
        SimpleNamespace(
            subject=f"角色{i}",
            attribute="背景",
            value="内容" * 500,
            description="说明" * 500,
            chapter_established=i,
        )
        for i in range(50)
    ]
    events = [
        SimpleNamespace(
            title=f"事件{i}",
            description="正文" * 500,
            story_day=i,
            chapter=i,
            foreshadowing="伏笔" * 500,
        )
        for i in range(50)
    ]

    context = build_story_bible_context(facts, events)

    joined = "\n".join(context)
    assert 0 < len(joined) <= MAX_STORY_BIBLE_CONTEXT_CHARS


@pytest.mark.asyncio
@pytest.mark.parametrize("current_day", [None, 3])
async def test_retrieve_context_reads_story_bible_and_records_trace(current_day):
    """检索节点读取事实/事件，并把裁剪后的上下文写回状态与 trace。"""
    facts = [
        SimpleNamespace(
            subject="林夏",
            attribute="身份",
            value="青州城守将",
            description=None,
            chapter_established=1,
        )
    ]
    events = [
        SimpleNamespace(
            title="初入青州",
            description="主角进入青州城。",
            story_day=2,
            chapter=2,
            foreshadowing=None,
        )
    ]
    service = AgentService.__new__(AgentService)
    state = {
        "novel_id": 1,
        "prompt": "主角进入青州城",
        "chapter": 3,
        "current_day": current_day,
        "workflow_steps": [],
    }

    with (
        patch(
            "app.services.generation.workflow.rag_service.retrieve_worldview",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.generation.workflow.rag_service.retrieve_character_info",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.generation.workflow.AgentService._load_context_pack_sync",
            return_value=(ContextPack("", build_story_bible_context(facts, events), "", {"sources": []}), 7, "story-life"),
        ) as load_context,
        patch("app.services.generation.workflow.AgentService._assert_context_scope_sync"),
        patch("app.services.generation.workflow.AgentService._load_consistency_reference_sync", return_value={}),
    ):
        result = await service._retrieve_context(state)

    load_context.assert_called_once_with(1, 3, current_day, None, None)
    assert result["story_bible_context"] == build_story_bible_context(facts, events)
    step = result["workflow_steps"][0]
    assert step["input"]["current_day"] == current_day
    assert step["output"]["story_bible_lines"] == len(result["story_bible_context"])
    assert step["data_sources"]["story_bible_context"] == result["story_bible_context"]


@pytest.mark.asyncio
async def test_agent_c_receives_story_bible_context_in_model_call():
    """剧情 Agent 必须拿到已确认事实，而不是只在 trace 里展示。"""
    service = AgentService.__new__(AgentService)
    service.llm_complex = object()
    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content="生成剧情")
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain
    state = {
        "prompt": "推进剧情",
        "worldview_output": "环境",
        "character_output": "人物",
        "story_bible_context": ["- 林夏的身份：青州城守将 [第1章确立]"],
        "target_length": 500,
        "consistency_result": {},
        "retry_count": 0,
        "workflow_steps": [],
    }

    with patch(
        "app.services.generation.workflow.ChatPromptTemplate.from_messages",
        return_value=prompt_template,
    ):
        result = await service._agent_c_plot(state)

    model_context = chain.ainvoke.await_args.args[0]
    assert "青州城守将" in model_context["story_bible_context"]
    assert result["workflow_steps"][0]["data_sources"]["story_bible_context"] == state[
        "story_bible_context"
    ]


@pytest.mark.parametrize("current_day, expected", [(None, [1]), (1, []), (2, [1]), (3, [3, 1])])
def test_generation_loader_keeps_chapter_scope_when_day_unknown(
    story_bible_db, monkeypatch, current_day, expected,
):
    """未知日不截掉第二天事件，明确日仍过滤，未来章节始终排除。"""
    story_bible_db.add(StoryEvent(
        id=20, novel_id=1, title="后续章节事件", description="不能出现在旧章",
        story_day=1, chapter=8, status="occurred",
    ))
    story_bible_db.commit()
    monkeypatch.setattr("app.services.generation.workflow.SessionLocal", lambda: story_bible_db)
    facts = get_active_facts_for_generation(story_bible_db, 1, max_chapter=3)
    events = get_events_for_generation(story_bible_db, 1, max_chapter=3, current_day=current_day)
    assert [event.id for event in events] == expected
    expected_context = build_story_bible_context(facts, events)
    pack, owner, lifecycle = AgentService._load_context_pack_sync(1, 3, current_day, 7, "story-life")
    assert (owner, lifecycle) == (7, "story-life")
    assert pack.story_bible_context == expected_context


@pytest.mark.parametrize("max_chapter, current_day, expected", [
    (3, None, [1]),
    (3, 3, [3, 1]),
    (3, 80, [30, 3, 1]),
    (None, None, [30, 3, 1]),
])
def test_unlocated_events_require_known_day_in_chapter_scoped_recall(
    story_bible_db, max_chapter, current_day, expected,
):
    """无章事件不能泄露给日期未知的旧章，明确日期或全局查询仍可读取。"""
    story_bible_db.add(StoryEvent(
        id=30, novel_id=1, title="终局事件", description="故事第八十天的结局",
        story_day=80, chapter=None, status="occurred",
    ))
    story_bible_db.commit()
    events = get_events_for_generation(
        story_bible_db, 1, max_chapter=max_chapter, current_day=current_day,
    )
    assert [event.id for event in events] == expected
    assert story_bible_db.get(StoryEvent, 30).description == "故事第八十天的结局"
