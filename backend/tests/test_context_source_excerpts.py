"""L0 下钻必须来自本轮已选中的有效来源，遵守既有预算。"""
from app.crud import novel as crud
from app.models.schemas import ChapterUpdate
from app.services.context.budget import MAX_STRUCTURED_CONTEXT_CHARS
from tests.test_context_builder import context_db, add_digest, build


def test_source_excerpt_uses_verified_prior_version(context_db):
    chapter, revision, _ = add_digest(context_db, 1)
    add_digest(context_db, 2)
    pack = build(context_db, 2)
    source = next(s for s in pack.manifest['structured_sources'] if s['kind'] == 'source_excerpt')
    assert source['source_refs'][0]['revision_id'] == revision.id
    assert chapter.content in pack.structured_context
    assert '第2次相遇' not in pack.structured_context
    assert len(pack.structured_context) <= MAX_STRUCTURED_CONTEXT_CHARS


def test_stale_digest_cannot_be_replaced_with_unrequested_raw_source(context_db):
    chapter, _, _ = add_digest(context_db, 1)
    crud.update_chapter(context_db, chapter.id, ChapterUpdate(expected_version=1, content='新稿没有剑。'))
    pack = build(context_db, 2)
    assert pack.digest_context == ''
    assert pack.structured_context == ''
    assert not pack.manifest['structured_sources']


def test_excerpt_names_source_chapter_instead_of_state_effective_chapter(context_db):
    """晚生效状态可引用早章，摘录标题必须标记原文实际章号。"""
    from types import SimpleNamespace
    from app.models.novel import Novel
    from app.models.story_memory import StoryEntity
    from app.services.memory import story as story_memory
    chapter, revision, _ = add_digest(context_db, 1)
    novel = context_db.get(Novel, 1)
    entity = StoryEntity(novel_id=1, novel_lifecycle_id=novel.rag_lifecycle_id, name='青霜剑', kind='item')
    context_db.add(entity)
    context_db.flush()
    story_memory.create_state(context_db, novel, SimpleNamespace(entity_id=entity.id, attribute='holder',
        value='林夏', value_entity_id=None, effective_chapter=3,
        source_refs=[dict(revision_id=revision.id, quote=chapter.content, start=0)]))
    context_db.commit()
    excerpts = [row for row in build(context_db, 4).manifest['structured_sources'] if row['kind'] == 'source_excerpt']
    assert len(excerpts) == 1
    assert excerpts[0]['title'] == '第1章原文摘录'
    assert excerpts[0]['effective_chapter'] == 1


def test_excerpt_count_budget_reports_unselected_verified_references(context_db):
    """实际选中简介包含多条不同出处时，原文下钻数量上限须报告省略。"""
    from app.services.memory.digest import validate_digest
    for number in range(1, 4):
        chapter, revision, digest = add_digest(context_db, number)
        payload = dict(summary=digest.summary, participants=[], events=[], state_change_candidates=[], open_threads=[],
            source_refs=[dict(quote=chapter.content, start=0), dict(quote=chapter.content[1:], start=1)])
        digest.source_refs = validate_digest(payload, revision)['source_refs']
    context_db.commit()
    pack = build(context_db, 4)
    assert len([row for row in pack.manifest['structured_sources'] if row['kind'] == 'source_excerpt']) == 3
    assert pack.manifest['omitted']['source_excerpt_limit'] == 3
    assert any('原文摘录' in warning for warning in pack.manifest['warnings'])
