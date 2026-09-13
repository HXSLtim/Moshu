"""正式账本经CRUD保存后进入请求级规则，无跨作品缓存污染。"""
import pytest
from app.crud import story_bible
from app.models.story_bible_schemas import FactCreate, EventCreate
from app.services.consistency_reference import load_consistency_reference
from app.services.consistency_service import ConsistencyService
from app.services.context_builder import ContextScopeError
from tests.test_projection_jobs import projection_db


@pytest.mark.asyncio
async def test_real_ledger_rules_are_used_without_global_mutation(projection_db):
    db, _, novel = projection_db
    story_bible.create_fact(db, FactCreate(novel_id=novel.id, subject='世界观', attribute='魔法等级上限', value='9', chapter_established=1))
    ref = load_consistency_reference(db, novel_id=novel.id, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id, chapter=2, current_day=None)
    service = ConsistencyService()
    result = await service.check_content(novel.id, '他是12级魔法师。', 2, None, reference=ref)
    assert result['has_conflict']
    assert result['layer_results']['rule_engine']['status'] == 'completed'
    assert service.rule_engine.rules_by_novel == {}
    before = load_consistency_reference(db, novel_id=novel.id, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id, chapter=1, current_day=None)
    assert before['rules']['魔法等级上限'] == 9
    with pytest.raises(ContextScopeError):
        load_consistency_reference(db, novel_id=novel.id, actor_id=novel.user_id+1, novel_lifecycle_id=novel.rag_lifecycle_id, chapter=2, current_day=None)


def test_future_and_free_text_not_compiled_as_hard_rules(projection_db):
    db, _, novel = projection_db
    story_bible.create_fact(db, FactCreate(novel_id=novel.id, subject='世界观', attribute='魔法等级上限', value='无限', chapter_established=1))
    story_bible.create_fact(db, FactCreate(novel_id=novel.id, subject='世界观', attribute='飞行速度上限', value='9', chapter_established=9))
    story_bible.create_event(db, EventCreate(novel_id=novel.id, title='计划', description='计划出城', story_day=1, chapter=1, status='planned'))
    ref = load_consistency_reference(db, novel_id=novel.id, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id, chapter=2, current_day=2)
    assert ref['rules'] == {}
    assert ref['timeline'] == []
    assert len(ref['unsupported_facts']) == 1
