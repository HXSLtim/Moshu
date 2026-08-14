"""写入 Schema 的上下文预算与历史读取兼容回归测试。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.character_schemas import (
    CharacterAppearanceCreate,
    CharacterOptimizationRequest,
    CharacterAppearanceResponse,
    CharacterRelationshipResponse,
    CharacterResponse,
)
from app.models.worldview_schemas import NovelAnalysisRequest, NovelOptimizationRequest
from app.models.schemas import (
    MAX_CHAPTER_CONTENT_CHARS,
    MAX_NOVEL_DESCRIPTION_CHARS,
    MAX_NOVEL_WORLDVIEW_CHARS,
    MAX_PLOT_OPTIONS_CONTENT_CHARS,
    MAX_RESEARCH_QUERY_CHARS,
    MAX_REWRITE_SOURCE_CHARS,
    MAX_STYLE_SAMPLE_CHARS,
    ChapterCreate,
    ChapterNextCreate,
    ChapterUpdate,
    InitNovelRequest,
    NovelCreate,
    NovelUpdate,
    PlotOptionsRequest,
    ResearchRequest,
    RewriteRequest,
    StyleSampleCreate,
    UserLogin,
    WorldviewCreate,
)


def test_chapter_storage_budget_keeps_normal_long_form_capacity():
    """章节存储上限远高于正常网文单章，但拒绝无界正文。"""
    normal_long_chapter = "正文" * 60_000

    assert ChapterCreate(
        chapter_number=1,
        title="长章节",
        content=normal_long_chapter,
    ).content == normal_long_chapter
    assert ChapterNextCreate(content=normal_long_chapter).content == normal_long_chapter
    assert ChapterUpdate(
        expected_version=1,
        content=normal_long_chapter,
    ).content == normal_long_chapter

    oversized = "x" * (MAX_CHAPTER_CONTENT_CHARS + 1)
    for schema, payload in (
        (ChapterCreate, {"chapter_number": 1, "title": "超限", "content": oversized}),
        (ChapterNextCreate, {"content": oversized}),
        (ChapterUpdate, {"expected_version": 1, "content": oversized}),
    ):
        with pytest.raises(ValidationError):
            schema(**payload)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            NovelCreate,
            {"title": "测试", "description": "x" * (MAX_NOVEL_DESCRIPTION_CHARS + 1)},
        ),
        (
            NovelUpdate,
            {"worldview": "x" * (MAX_NOVEL_WORLDVIEW_CHARS + 1)},
        ),
        (
            StyleSampleCreate,
            {
                "novel_id": 1,
                "name": "样本",
                "sample_text": "x" * (MAX_STYLE_SAMPLE_CHARS + 1),
            },
        ),
        (
            InitNovelRequest,
            {"novel_id": 1, "target_chapters": 81},
        ),
        (
            InitNovelRequest,
            {"novel_id": 1, "theme": "x" * 1_001},
        ),
        (
            PlotOptionsRequest,
            {
                "novel_id": 1,
                "chapter_id": 1,
                "current_content": "x" * (MAX_PLOT_OPTIONS_CONTENT_CHARS + 1),
            },
        ),
        (
            RewriteRequest,
            {
                "novel_id": 1,
                "original_text": "x" * (MAX_REWRITE_SOURCE_CHARS + 1),
            },
        ),
        (
            RewriteRequest,
            {"novel_id": 1, "original_text": "原文", "rewrite_type": "unknown"},
        ),
        (
            ResearchRequest,
            {"query": "x" * (MAX_RESEARCH_QUERY_CHARS + 1)},
        ),
        (
            UserLogin,
            {"username": "x" * 51, "password": "secret1"},
        ),
        (
            UserLogin,
            {"username": "reader", "password": "x" * 51},
        ),
    ],
)
def test_active_write_requests_reject_oversized_or_invalid_input(schema, payload):
    """进入持久化、模型或外部检索链路前就拒绝超预算输入。"""
    with pytest.raises(ValidationError):
        schema(**payload)


def test_write_requests_reject_unknown_fields_and_nested_rule_bombs():
    """未声明字段和藏在 Any 值中的大块嵌套数据都不能绕过预算。"""
    with pytest.raises(ValidationError):
        ResearchRequest(query="古罗马", ignored="客户端拼写错误")

    with pytest.raises(ValidationError):
        UserLogin(username="reader", password="secret1", ignored=True)

    with pytest.raises(ValidationError):
        NovelUpdate()

    assert NovelUpdate(description=None).model_fields_set == {"description"}

    with pytest.raises(ValidationError):
        WorldviewCreate(
            novel_id=1,
            name="力量体系",
            content="世界观",
            rules=[
                {
                    "name": "隐藏规则",
                    "value": {"payload": "x" * 50_000},
                }
            ],
        )


def test_character_read_models_accept_legacy_values_without_weakening_writes():
    """新写入规则不应让历史角色、关系和出场记录在读取时变成 500。"""
    now = datetime.now()
    legacy_character = SimpleNamespace(
        id=1,
        novel_id=1,
        name="旧角色",
        age=2_000,
        gender=None,
        occupation=None,
        appearance="x" * 4_001,
        personality=None,
        background="x" * 8_001,
        skills=["x" * 201] * 51,
        relationships={"legacy": "x"},
        character_arc=None,
        importance_level="protagonist",
        first_appearance_chapter=0,
        last_appearance_chapter=-1,
        ai_analysis={},
        created_at=now,
        updated_at=now,
    )

    character = CharacterResponse.model_validate(legacy_character)
    relationship = CharacterRelationshipResponse(
        id=1,
        novel_id=1,
        character_a_id=1,
        character_b_id=2,
        relationship_type="legacy",
        description="x" * 4_001,
        strength=0,
        development_stage="unknown",
        established_in_chapter=0,
        character_a_name="甲",
        character_b_name="乙",
        created_at=now,
        updated_at=now,
    )
    appearance = CharacterAppearanceResponse(
        id=1,
        character_id=1,
        chapter_id=1,
        appearance_type="legacy",
        description="x" * 4_001,
        importance_in_chapter=0,
        character_name="甲",
        chapter_number=0,
        created_at=now,
    )

    assert character.importance_level == "protagonist"
    assert len(character.skills or []) == 51
    assert relationship.established_in_chapter == 0
    assert appearance.appearance_type == "legacy"


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (
            CharacterOptimizationRequest,
            {"character_id": 1, "optimization_goals": ["x" * 501]},
        ),
        (
            CharacterAppearanceCreate,
            {
                "character_id": 1,
                "chapter_id": 1,
                "status_changes": {"payload": "x" * 20_000},
            },
        ),
        (
            NovelAnalysisRequest,
            {"novel_id": 1, "analysis_scope": ["plot"] * 11},
        ),
        (
            NovelOptimizationRequest,
            {
                "novel_id": 1,
                "optimization_goals": ["x" * 501],
                "target_areas": ["plot"],
            },
        ),
    ],
)
def test_adjacent_ai_request_schemas_have_nested_budgets(schema, payload):
    """角色与整体小说分析的数组、嵌套字典也不能绕过主预算。"""
    with pytest.raises(ValidationError):
        schema(**payload)
