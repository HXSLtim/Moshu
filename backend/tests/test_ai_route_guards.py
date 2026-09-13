"""AI 路由输入契约与所有权防线测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.consistency import ConsistencyCheckRequest, check_consistency_stream
from app.api.routes.generation import ContinueRequest, generate_content, init_novel, parse_idea
from app.api.routes.review import ChapterReviewRequest, _get_owned_chapter
from app.models.schemas import GenerationRequest, IdeaParseRequest, InitNovelRequest


def test_review_and_consistency_routes_require_auth(client):
    review_response = client.post(
        "/api/review/chapter",
        json={
            "novel_id": 1,
            "chapter_id": 1,
            "chapter_number": 1,
            "content": "正文",
        },
    )
    consistency_response = client.post(
        "/api/consistency/check-stream",
        json={
            "novel_id": 1,
            "chapter": 1,
            "content": "正文",
        },
    )

    assert review_response.status_code == 403
    assert consistency_response.status_code == 403


@pytest.mark.asyncio
async def test_init_novel_uses_valid_request_fields():
    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(
        content=(
            '{"worldview":"世界",'
            '"main_characters":["主角"],'
            '"outline":"大纲",'
            '"plot_hooks":["伏笔"]}'
        )
    )
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain
    novel = MagicMock(
        id=1,
        user_id=1,
        title="测试小说",
        genre="玄幻",
        description="简介",
    )

    with (
        patch(
            "app.api.routes.generation.novel_crud.get_novel_by_id",
            return_value=novel,
        ),
        patch(
            "app.api.routes.generation.ChatPromptTemplate.from_messages",
            return_value=prompt_template,
        ),
    ):
        result = await init_novel.__wrapped__(
            InitNovelRequest(novel_id=1, target_chapters=10, theme="成长"),
            MagicMock(id=1),
            MagicMock(),
        )

    assert result.worldview == "世界"
    assert result.main_characters == ["主角"]


def test_continue_request_rejects_invalid_controls():
    with pytest.raises(ValidationError):
        ContinueRequest(
            novel_id=1,
            chapter_id=1,
            current_content="正文",
            target_length=50,
            pace="极速",
            tone="未知",
            style_strength=2,
        )


@pytest.mark.asyncio
async def test_parse_idea_returns_validated_structured_draft():
    """想法解析返回严格结构草案；全书用卷覆盖，开头才逐章展开。"""
    draft = {
        "title": "旧收音机",
        "genre": "都市奇幻",
        "description": "一位修复师听见旧物里的声音。",
        "worldview": "旧物会保留与其相处最久之人的记忆。",
        "planned_chapters": 300,
        "arcs": [
            {"name": "第一部 潮声", "chapter_start": 1, "chapter_end": 120, "summary": "修复师追查旧收音机的来历。"},
            {"name": "第二部 灯塔", "chapter_start": 121, "chapter_end": 300, "summary": "旧物记忆牵出三十年前的旧案。"},
        ],
        "characters": [
            {"name": "沈砚", "role": "主角", "personality": "执拗", "goal": "找到失主"},
        ],
        "opening_outline": [
            {"chapter_number": 1, "title": "频率", "summary": "收到旧收音机", "conflict": "声音不该存在", "outcome": "决定追查"},
            {"chapter_number": 2, "title": "回声", "summary": "找到线索", "conflict": "线索指向家人", "outcome": "确认姐姐失踪"},
        ],
        "plot_hooks": ["收音机的真正来源"],
        "uncertainties": ["姐姐是否存活尚未确定"],
    }
    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content=__import__("json").dumps(draft, ensure_ascii=False))
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain

    with patch(
        "app.api.routes.generation.ChatPromptTemplate.from_messages",
        return_value=prompt_template,
    ):
        result = await parse_idea(
            IdeaParseRequest(idea="会听旧物记忆的修复师", planned_chapters=300),
            MagicMock(id=1),
        )

    assert result.title == "旧收音机"
    assert result.planned_chapters == 300
    assert [item.chapter_number for item in result.opening_outline] == [1, 2]
    assert (result.arcs[0].chapter_start, result.arcs[-1].chapter_end) == (1, 300)
    assert result.uncertainties == ["姐姐是否存活尚未确定"]


@pytest.mark.asyncio
async def test_parse_idea_rejects_arcs_that_do_not_cover_the_book():
    """卷/阶段没有连续覆盖全书时明确失败，不创建半成品项目。"""
    bad = {
        "title": "旧收音机", "genre": "都市奇幻", "description": "简介", "worldview": "世界",
        "planned_chapters": 300,
        "arcs": [{"name": "第一部", "chapter_start": 1, "chapter_end": 120, "summary": "开场"}],
        "characters": [{"name": "沈砚", "role": "主角", "personality": "执拗", "goal": "找到失主"}],
        "opening_outline": [{"chapter_number": 1, "title": "频率", "summary": "收到", "conflict": "冲突", "outcome": "结果"}],
        "plot_hooks": ["线索"], "uncertainties": [],
    }
    chain = AsyncMock()
    chain.ainvoke.return_value = SimpleNamespace(content=__import__("json").dumps(bad, ensure_ascii=False))
    prompt_template = MagicMock()
    prompt_template.__or__.return_value = chain

    with patch(
        "app.api.routes.generation.ChatPromptTemplate.from_messages",
        return_value=prompt_template,
    ):
        with pytest.raises(HTTPException) as exc:
            await parse_idea(
                IdeaParseRequest(idea="想法", planned_chapters=300),
                MagicMock(id=1),
            )

    assert exc.value.status_code == 422




def test_review_request_limits_previous_chapter_count():
    with pytest.raises(ValidationError):
        ChapterReviewRequest(
            novel_id=1,
            chapter_id=1,
            chapter_number=1,
            content="正文",
            previous_chapters=["前文"] * 4,
        )


@pytest.mark.asyncio
async def test_generate_rejects_foreign_novel_before_agent_call():
    user = MagicMock(id=1)
    foreign_novel = MagicMock(user_id=2)
    agent_call = AsyncMock()
    with (
        patch("app.api.routes.generation.novel_crud.get_novel_by_id", return_value=foreign_novel),
        patch("app.api.routes.generation.agent_service.generate_content", agent_call),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await generate_content.__wrapped__(
                GenerationRequest(novel_id=9, prompt="剧情", chapter=1, target_length=500),
                user,
                MagicMock(),
            )

    assert exc_info.value.status_code == 404
    agent_call.assert_not_awaited()


def test_review_rejects_foreign_novel_before_chapter_lookup():
    request = ChapterReviewRequest(
        novel_id=9,
        chapter_id=3,
        chapter_number=1,
        content="正文",
    )
    with (
        patch("app.api.routes.review.novel_crud.get_novel_by_id", return_value=MagicMock(user_id=2)),
        patch("app.api.routes.review.novel_crud.get_chapter_by_id") as chapter_lookup,
    ):
        with pytest.raises(HTTPException) as exc_info:
            _get_owned_chapter(MagicMock(), MagicMock(id=1), request)

    assert exc_info.value.status_code == 404
    chapter_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_consistency_rejects_foreign_novel_before_check():
    request = ConsistencyCheckRequest(
        novel_id=9,
        chapter=1,
        content="正文",
    )
    with patch(
        "app.api.routes.consistency.novel_crud.get_novel_by_id",
        return_value=MagicMock(user_id=2),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await check_consistency_stream(
                request,
                MagicMock(),
                MagicMock(id=1),
                MagicMock(),
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_consistency_stream_emits_explicit_done_event():
    async def fake_check_stream(**kwargs):
        yield {"type": "summary", "has_conflict": False}

    http_request = MagicMock()
    http_request.is_disconnected = AsyncMock(return_value=False)
    with (
        patch(
            "app.api.routes.consistency.novel_crud.get_novel_by_id",
            return_value=MagicMock(user_id=1),
        ),
        patch(
            "app.api.routes.consistency.novel_crud.get_chapter_by_number",
            return_value=MagicMock(novel_id=1),
        ),
        patch(
            "app.api.routes.consistency.consistency_service.check_content_stream",
            side_effect=fake_check_stream,
        ),
        patch("app.api.routes.consistency.load_consistency_reference", return_value={}),
    ):
        response = await check_consistency_stream(
            ConsistencyCheckRequest(novel_id=1, chapter=1, content="正文"),
            http_request,
            MagicMock(id=1),
            MagicMock(),
        )
        chunks = [chunk async for chunk in response.body_iterator]

    payload = "".join(
        chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
        for chunk in chunks
    )
    assert '"type": "summary"' in payload
    assert '"type": "done"' in payload
