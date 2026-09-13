"""高级生成以真实数据库记忆构建 Prompt，并在异步检索前后守住身份边界。"""
import hashlib
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crud import novel as novel_crud
from app.db.base import Base
from app.models.memory import ChapterDigest, ChapterRevision
from app.models.novel import Novel
from app.models.schemas import ChapterCreate, ChapterUpdate, GenerationRequest
from app.models.user import User
from app.services.agent_service import AgentService
from app.services.context_builder import build_context_pack
from app.services.memory_config import digest_recipe_version


def _add_digest(db, chapter, summary, recipe=None):
    revision = db.query(ChapterRevision).filter_by(chapter_id=chapter.id, version=chapter.version).one()
    digest = ChapterDigest(
        novel_id=chapter.novel_id, chapter_id=chapter.id, source_revision_id=revision.id,
        recipe_version=recipe or digest_recipe_version(), summary=summary,
        state_change_candidates=['禁止作为确认事实注入的候选变化'],
        source_refs=[dict(revision_id=revision.id, content_hash=revision.content_hash,
                          start=0, end=len(revision.content), quote=revision.content,
                          quote_hash=hashlib.sha256(revision.content.encode()).hexdigest())],
    )
    db.add(digest); db.commit()
    return digest


@pytest.fixture
def generation_memory(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([User(id=1, username='作者', email='author@test.cn', hashed_password='unused'),
                    User(id=2, username='他人', email='other@test.cn', hashed_password='unused')])
        db.add_all([Novel(id=1, user_id=1, title='当前小说', worldview='作者世界观', rag_lifecycle_id='current-life'),
                    Novel(id=2, user_id=2, title='他人小说')]); db.commit()
        chapters = [novel_crud.create_chapter(db, 1, ChapterCreate(chapter_number=n, title=f'章节{n}', content=f'第{n}章原文。')) for n in range(1, 5)]
        good = _add_digest(db, chapters[0], '青霜剑藏在{旧塔}，面板为{"灵力":9}。')
        _add_digest(db, chapters[0], '旧配方禁止注入', recipe='outdated-recipe')
        _add_digest(db, chapters[1], '旧原文禁止注入')
        novel_crud.update_chapter(db, chapters[1].id, ChapterUpdate(expected_version=1, content='作者已经改稿。'))
        _add_digest(db, chapters[2], '当前章简介禁止注入')
        _add_digest(db, chapters[3], '未来章简介禁止注入')
        foreign = novel_crud.create_chapter(db, 2, ChapterCreate(chapter_number=1, title='他人首章', content='他人原文。'))
        _add_digest(db, foreign, '其他作者禁止注入')
        expected_pack = build_context_pack(db, novel_id=1, actor_id=1, novel_lifecycle_id='current-life', target_chapter=3)
        good_id = good.id
    monkeypatch.setattr('app.services.agent_service.SessionLocal', sessions)
    yield sessions, expected_pack, good_id
    engine.dispose()


def _service_with_real_prompts(monkeypatch):
    seen = []
    async def answer(prompt):
        seen.append('\n'.join(message.content for message in prompt.to_messages()))
        return AIMessage(content='候选正文', response_metadata={'finish_reason': 'stop'})
    service = AgentService.__new__(AgentService)
    service.llm_simple = service.llm_complex = RunnableLambda(answer)
    async def consistency(_state):
        return {'consistency_result': {'has_conflict': False, 'is_complete': False, 'checks_skipped': ['knowledge_graph']}}
    service._consistency_check = consistency
    service.workflow = service._build_workflow()
    worldview = AsyncMock(return_value=[])
    characters = AsyncMock(return_value=[])
    monkeypatch.setattr('app.services.agent_service.rag_service.retrieve_worldview', worldview)
    monkeypatch.setattr('app.services.agent_service.rag_service.retrieve_character_info', characters)
    return service, seen, worldview, characters


@pytest.mark.asyncio
@pytest.mark.parametrize('stream', [False, True])
async def test_database_digest_reaches_every_real_prompt_and_response_manifest(generation_memory, monkeypatch, stream):
    """A/B/C 实际模型输入只含有效前章简介，普通与流式响应保留同一份来源清单。"""
    _, expected_pack, good_id = generation_memory
    service, seen, _, _ = _service_with_real_prompts(monkeypatch)
    request = GenerationRequest(novel_id=1, chapter=3, prompt='继续写作')
    scope = dict(actor_id=1, novel_lifecycle_id='current-life')
    if stream:
        events = [event async for event in service.generate_content_stream(request, **scope)]
        response = events[-1]['data']
        retrieval = next(event for event in events if event.get('status') == '上下文检索完成')
        assert retrieval['data']['context_manifest'] == response.context_manifest
    else:
        response = await service.generate_content(request, **scope)
    assert len(seen) == 3
    assert response.context_manifest == expected_pack.manifest
    assert [source['id'] for source in response.context_manifest['sources']] == [good_id]
    for prompt in seen:
        assert expected_pack.digest_context in prompt
        assert 'AI 提取参考，不是作者确认事实' in prompt
        for forbidden in ['旧配方禁止注入', '旧原文禁止注入', '当前章简介禁止注入', '未来章简介禁止注入', '其他作者禁止注入', '禁止作为确认事实注入的候选变化']:
            assert forbidden not in prompt
    for step in response.workflow_trace.steps:
        assert step.data_sources['context_manifest'] == expected_pack.manifest


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', [dict(actor_id=2, novel_lifecycle_id='current-life'),
                                  dict(actor_id=1, novel_lifecycle_id='old-life'),
                                  dict(actor_id=1, novel_lifecycle_id=None)])
async def test_invalid_scope_stops_before_vector_or_model_access(generation_memory, monkeypatch, scope):
    """伪造作者、旧生命周期或不完整身份均在任何检索和模型调用之前失败。"""
    service, seen, worldview, characters = _service_with_real_prompts(monkeypatch)
    with pytest.raises(ValueError):
        await service.generate_content(GenerationRequest(novel_id=1, chapter=3, prompt='继续'), **scope)
    worldview.assert_not_awaited(); characters.assert_not_awaited()
    assert not seen


@pytest.mark.asyncio
async def test_scope_changed_during_rag_cannot_reach_model(generation_memory, monkeypatch):
    """即使向量服务读到复用 ID 的新书，检索后复核仍阻断模型输入。"""
    sessions, _, _ = generation_memory
    service, seen, _, _ = _service_with_real_prompts(monkeypatch)
    async def raced_retrieval(**_):
        with sessions() as db:
            db.execute(update(Novel).where(Novel.id == 1).values(rag_lifecycle_id='replacement-life'))
            db.commit()
        return ['不能进入模型的新生命周期内容']
    monkeypatch.setattr('app.services.agent_service.rag_service.retrieve_worldview', raced_retrieval)
    with pytest.raises(ValueError, match='生命周期'):
        await service.generate_content(GenerationRequest(novel_id=1, chapter=3, prompt='继续'), actor_id=1, novel_lifecycle_id='current-life')
    assert not seen


def test_internal_call_resolves_scope_once_without_unbounded_fallback(generation_memory):
    """内部调用允许从真实小说解析作用域，但不存在的小说不能降级为全库召回。"""
    _, expected_pack, _ = generation_memory
    pack, owner, lifecycle = AgentService._load_context_pack_sync(1, 3, None, None, None)
    assert (owner, lifecycle) == (1, 'current-life')
    assert pack.manifest == expected_pack.manifest
    with pytest.raises(ValueError, match='不存在'):
        AgentService._load_context_pack_sync(999, 3, None, None, None)
