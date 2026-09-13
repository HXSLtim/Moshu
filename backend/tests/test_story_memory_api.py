"""真实隔离路由验证结构化记忆的权限、时态、审阅和来源事务。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.api.dependencies import get_current_user
from app.api.routes import story_memory as routes
from app.crud import novel as chapters
from app.db.base import Base, get_db, _set_sqlite_pragmas
from app.models.memory import ChapterRevision
from app.models.novel import Novel, Chapter
from app.models.schemas import ChapterCreate, ChapterUpdate
from app.models.story_bible import StoryFact
from app.models.story_memory import StoryEntity, OutlineNode, StateCandidate, StoryMemoryCommand, StoryMemoryHead
from app.models.user import User
from app.services import story_memory as memory
from app.services.story_memory_extractor import StoryExtraction


@pytest.fixture
def memory_api():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    db = factory()
    db.add_all([User(id=1, username='作者', email='one@example.com', hashed_password='x'),
                User(id=2, username='另一个作者', email='two@example.com', hashed_password='x')])
    db.commit()
    db.add_all([Novel(id=1, title='青霜剑', user_id=1), Novel(id=2, title='另一本书', user_id=2)])
    db.commit()
    for number, content in [(3, '林夏获得青霜剑。'), (12, '林夏把青霜剑交给阿宁保管。'), (30, '阿宁遗失了青霜剑。')]:
        chapters.create_chapter(db, 1, ChapterCreate(chapter_number=number, title=f'第{number}章', content=content))
    chapters.create_chapter(db, 2, ChapterCreate(chapter_number=1, title='他人原文', content='不应被读取。'))
    current_user = SimpleNamespace(id=1)
    application = FastAPI()
    application.include_router(routes.router, prefix='/api')
    def override_db():
        with factory() as session:
            yield session
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_user] = lambda: current_user
    client = TestClient(application)
    yield SimpleNamespace(client=client, db=db, factory=factory, user=current_user, engine=engine)
    db.close()
    engine.dispose()


def snapshot(api, novel=1, chapter=None):
    response = api.client.get(f'/api/novels/{novel}/story-memory', params={'chapter': chapter} if chapter else {})
    assert response.status_code == 200, response.text
    return response.json()


def command(api, path, data=None, *, method='post', novel=1, status=200, request=None):
    current = snapshot(api, novel)
    body = request or dict(request_id=str(uuid4()), expected_version=current['version'],
                           novel_lifecycle_id=current['novel_lifecycle_id'], **(data or {}))
    response = getattr(api.client, method)(f'/api/novels/{novel}/story-memory{path}', json=body)
    assert response.status_code == status, response.text
    return response.json(), body


def entity(api, name='青霜剑', kind='item'):
    result, _ = command(api, '/entities', dict(name=name, kind=kind))
    return next(row['id'] for row in result['entities'] if row['name'] == name)


def source(api, number=3, novel=1):
    api.db.expire_all()
    revision = api.db.query(ChapterRevision).filter_by(novel_id=novel, chapter_number=number).order_by(ChapterRevision.version.desc()).first()
    return {'revision_id': revision.id, 'quote': revision.content, 'start': 0}


def state(api, item, value, number=3, attribute='holder', candidate=False, target=None, refs=None):
    data = dict(entity_id=item, attribute=attribute, value=value, value_entity_id=target,
                effective_chapter=number, source_refs=refs if refs is not None else [source(api, number)])
    return command(api, '/candidates' if candidate else '/states', data)[0]


def outline(api, **overrides):
    data = dict(kind='chapter', plot_status='planned', chapter_number=12, title='计划转交', source_refs=[])
    data.update(overrides)
    return command(api, '/outline', data)[0]['outline_nodes'][-1]


def test_transfer_keeps_owner_holder_quantity_separate_and_respects_history(memory_api):
    """第 8/20/35 章分别取获得、转交、遗失状态，所有权不随保管自动变更。"""
    api = memory_api
    sword = entity(api)
    hero = entity(api, '林夏', 'character')
    friend = entity(api, '阿宁', 'character')
    state(api, sword, '将由实体名规范化', attribute='owner', target=hero)
    state(api, sword, '林夏', target=hero)
    state(api, sword, '0001', attribute='quantity')
    state(api, sword, '阿宁', number=12, target=friend)
    state(api, sword, '遗失', number=30)
    for chapter, holder in [(8, '林夏'), (20, '阿宁'), (35, '遗失')]:
        rows = {row['attribute']: row for row in snapshot(api, chapter=chapter)['states']}
        assert rows['holder']['value'] == holder
        assert rows['owner']['value_entity_id'] == hero
        assert rows['quantity']['value'] == '1'
    assert snapshot(api, chapter=2)['states'] == []
    assert len(snapshot(api)['state_history']) == 5


@pytest.mark.parametrize('value', ['-1', '1.5', '一', '１２', '1000000000000'])
def test_quantity_rejects_invalid_totals_without_advancing_version(memory_api, value):
    api = memory_api
    sword = entity(api)
    before = snapshot(api)
    command(api, '/states', dict(entity_id=sword, attribute='quantity', value=value, effective_chapter=3), status=422)
    assert snapshot(api) == before


def test_names_and_entity_targets_do_not_guess_identity_or_cross_novels(memory_api):
    api = memory_api
    sword = entity(api)
    command(api, '/entities', dict(name=' 青霜剑 ', kind='character'))
    foreign = StoryEntity(novel_id=2, novel_lifecycle_id=api.db.get(Novel, 2).rag_lifecycle_id, name='林夏', kind='character')
    api.db.add(foreign)
    api.db.commit()
    command(api, '/states', dict(entity_id=sword, attribute='holder', value='林夏', value_entity_id=foreign.id,
                                effective_chapter=3), status=404)
    command(api, '/states', dict(entity_id=foreign.id, attribute='身份', value='主角', effective_chapter=3), status=404)
    assert len(snapshot(api)['entities']) == 2


def test_candidate_decisions_replay_once_and_compare_payload_and_version(memory_api):
    api = memory_api
    sword = entity(api)
    proposed = state(api, sword, '林夏', candidate=True)
    candidate = proposed['candidates'][0]['id']
    assert proposed['states'] == []
    confirmed, request = command(api, f'/candidates/{candidate}/decision', dict(action='confirm'))
    replay, _ = command(api, f'/candidates/{candidate}/decision', request=request)
    assert replay == confirmed
    assert len(replay['state_history']) == 1
    command(api, f'/candidates/{candidate}/decision', request={**request, 'action': 'reject'}, status=409)
    command(api, '/entities', request={**request, 'request_id': str(uuid4()), 'name': '旧请求', 'kind': 'character', 'action': 'confirm'}, status=422)
    command(api, '/entities', dict(name='阿宁', kind='character'))
    revoked, revoke_request = command(api, f'/candidates/{candidate}/decision', dict(action='revoke', reason='作者撤销'))
    assert revoked['states'] == [] and revoked['state_history'][0]['status'] == 'revoked'
    assert command(api, f'/candidates/{candidate}/decision', request=revoke_request)[0] == revoked
    current = snapshot(api)
    command(api, '/entities', request={**request, 'request_id': str(uuid4()), 'name': '过时', 'kind': 'character'} | {'action': 'confirm'}, status=422)
    command(api, '/entities', request=dict(request_id=str(uuid4()), expected_version=0,
        novel_lifecycle_id=current['novel_lifecycle_id'], name='过时', kind='character'), status=409)


def test_reject_then_reextract_cannot_resurrect_candidate(memory_api):
    api = memory_api
    sword = entity(api)
    candidate = state(api, sword, '林夏', candidate=True)['candidates'][0]['id']
    rejected, request = command(api, f'/candidates/{candidate}/decision', dict(action='reject'))
    assert command(api, f'/candidates/{candidate}/decision', request=request)[0] == rejected
    assert state(api, sword, '林夏', candidate=True)['candidates'][0]['status'] == 'rejected'
    assert len(snapshot(api)['candidates']) == 1
    command(api, f'/candidates/{candidate}/decision', dict(action='confirm'), status=409)


def test_sources_are_owned_exact_and_not_from_future(memory_api):
    api = memory_api
    sword = entity(api)
    base = dict(entity_id=sword, attribute='holder', value='林夏', effective_chapter=3)
    for refs, code in [([source(api, 12)], 422), ([source(api, 1, novel=2)], 404),
                       ([{**source(api), 'start': 1}], 422), ([{**source(api), 'quote': '原文没有'}], 422)]:
        command(api, '/candidates', dict(**base, source_refs=refs), status=code)
    assert snapshot(api)['candidates'] == []


def test_source_edit_marks_cross_attribute_dependents_and_preserves_author_records(memory_api):
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏')
    state(api, sword, '阿宁', number=12)
    state(api, sword, '0', number=30, attribute='quantity')
    plan = outline(api)
    outline(api, plot_status='occurred', chapter_number=30, title='实际遗失', source_refs=[source(api, 30)])
    before = snapshot(api)
    chapter = api.db.query(Chapter).filter_by(novel_id=1, chapter_number=12).one()
    chapters.update_chapter(api.db, chapter.id, ChapterUpdate(expected_version=1, content='林夏没有转交青霜剑。'))
    changed = snapshot(api)
    assert changed['version'] > before['version']
    assert changed['states'] == []
    assert next(row for row in changed['outline_nodes'] if row['id'] == plan['id']) == plan
    assert all(row['source_status'] == 'needs_review' for row in changed['state_history'] if row['chapter_established'] >= 12)
    assert {row['value'] for row in snapshot(api, chapter=8)['states']} == {'林夏'}
    quantity = next(row for row in changed['state_history'] if row['attribute'] == 'quantity')
    command(api, f"/states/{quantity['id']}/resolve", dict(source_refs=[source(api, 30)], reason='作者核对本章仍然遗失'))
    assert {row['value'] for row in snapshot(api, chapter=35)['states']} == {'0'}
    assert len(snapshot(api)['state_history']) == 3


def test_raw_source_change_is_excluded_from_read_even_before_invalidation(memory_api):
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏')
    api.db.execute(text("UPDATE chapters SET content='未经标准保存修改' WHERE novel_id=1 AND chapter_number=3"))
    api.db.commit()
    result = snapshot(api, chapter=8)
    assert result['states'] == [] and result['warnings']


def test_raw_source_change_blocks_later_cross_attribute_states_until_review(memory_api):
    """绕过保存的前置持有变化也阻断后续数量，早于失效点的所有权仍然有效。"""
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏', attribute='owner')
    state(api, sword, '阿宁', number=12)
    state(api, sword, '0', number=30, attribute='quantity')
    api.db.execute(text("UPDATE chapters SET content='未交给阿宁' WHERE novel_id=1 AND chapter_number=12"))
    api.db.commit()
    result = snapshot(api, chapter=35)
    assert [row['attribute'] for row in result['states']] == ['owner']
    quantity = next(row for row in result['state_history'] if row['attribute'] == 'quantity')
    restored, _ = command(api, f"/states/{quantity['id']}/resolve", dict(
        source_refs=[source(api, 30)], reason='作者确认遗失数量仍成立'))
    assert {row['attribute'] for row in restored['states']} == {'owner', 'quantity'}


def test_move_replacement_marks_dependencies_after_old_position(memory_api):
    api = memory_api
    sword = entity(api)
    old = state(api, sword, '林夏')['state_history'][0]
    state(api, sword, '阿宁', number=12)
    result, _ = command(api, f"/states/{old['id']}/replace", dict(entity_id=sword, attribute='holder',
        value='已归还林夏', effective_chapter=30, source_refs=[source(api, 30)]))
    dependent = next(row for row in result['state_history'] if row['chapter_established'] == 12)
    assert dependent['source_status'] == 'needs_review'
    assert next(row for row in result['state_history'] if row['id'] == old['id'])['status'] == 'revoked'


def test_moving_source_chapter_marks_outline_after_its_old_position(memory_api):
    """前章后移时按旧、新位置的较早点传播依赖，不能漏掉夹在其间的实际大纲。"""
    api = memory_api
    plan = outline(api)
    occurred = outline(api, plot_status='occurred', chapter_number=30,
        title='第三十章的实际结果', source_refs=[source(api, 30)])
    chapter = api.db.query(Chapter).filter_by(novel_id=1, chapter_number=12).one()
    chapters.update_chapter(api.db, chapter.id, ChapterUpdate(expected_version=1, chapter_number=35))
    result = snapshot(api)
    assert next(row for row in result['outline_nodes'] if row['id'] == occurred['id'])['source_status'] == 'needs_review'
    assert next(row for row in result['outline_nodes'] if row['id'] == plan['id']) == plan
    assert memory.get_outline_for_generation(api.db, 1, 40) == []


def test_outline_hierarchy_scope_and_future_plan_filter(memory_api):
    api = memory_api
    volume = outline(api, kind='volume', chapter_number=None, title='第一卷')
    chapter = outline(api, parent_id=volume['id'])
    scene = dict(kind='scene', plot_status='planned', chapter_number=12, title='交剑', parent_id=chapter['id'])
    command(api, '/outline', scene)
    command(api, '/outline', {**scene, 'parent_id': volume['id']}, status=422)
    command(api, '/outline', {**scene, 'chapter_number': 30}, status=422)
    command(api, '/outline', {**scene, 'plot_status': 'occurred'}, status=422)
    command(api, f"/outline/{chapter['id']}", dict(kind='chapter', plot_status='planned', chapter_number=30,
        title='挪动章节', parent_id=volume['id']), method='put', status=409)
    assert memory.get_outline_for_generation(api.db, 1, 3) == []
    assert len(memory.get_outline_for_generation(api.db, 1, 3, include_plans=True)) == 3


def extraction_payload(api, sword):
    quote = source(api)
    refs = [{'quote': quote['quote'], 'start': 0}]
    return StoryExtraction.model_validate({'outline': [{'title': '获得宝剑', 'conflict': '', 'outcome': '得到剑', 'source_refs': refs}],
        'states': [{'entity_id': sword, 'attribute': 'holder', 'value': '林夏', 'value_entity_id': None, 'source_refs': refs}]})


def test_extraction_is_atomic_deduplicates_and_never_overwrites_plan(memory_api, monkeypatch):
    api = memory_api
    sword = entity(api)
    plan = outline(api)
    payload = extraction_payload(api, sword)
    payload.states.append(payload.states[0])
    payload.outline.append(payload.outline[0])
    async def extract(*_):
        return payload
    monkeypatch.setattr(routes.story_memory_extractor, 'extract', extract)
    body = dict(source_revision_id=source(api)['revision_id'])
    first, request = command(api, '/extract', body)
    assert first['states'] == [] and len(first['candidates']) == 1 and len(first['outline_nodes']) == 2
    assert command(api, '/extract', request=request)[0] == first
    second, _ = command(api, '/extract', body)
    assert {row['id'] for row in first['outline_nodes']} == {row['id'] for row in second['outline_nodes']}
    assert next(row for row in second['outline_nodes'] if row['id'] == plan['id']) == plan
    payload.outline[0].source_refs[0].quote = '虚构引用'
    command(api, '/extract', body, status=422)
    assert snapshot(api) == second


def test_extraction_discards_late_response_and_stale_version_before_model_call(memory_api, monkeypatch):
    api = memory_api
    sword = entity(api)
    old = source(api)['revision_id']
    payload = extraction_payload(api, sword)
    calls = []
    async def extract(*_):
        calls.append(1)
        with api.factory() as session:
            chapter = session.query(Chapter).filter_by(novel_id=1, chapter_number=3).one()
            chapters.update_chapter(session, chapter.id, ChapterUpdate(expected_version=1, content='林夏没有获得剑。'))
        return payload
    monkeypatch.setattr(routes.story_memory_extractor, 'extract', extract)
    current = snapshot(api)
    request = dict(request_id=str(uuid4()), expected_version=0, novel_lifecycle_id=current['novel_lifecycle_id'], source_revision_id=old)
    command(api, '/extract', request=request, status=409)
    assert calls == []
    command(api, '/extract', dict(source_revision_id=old), status=409)
    assert calls == [1]
    assert snapshot(api)['candidates'] == []


def test_permissions_deletion_and_reused_ids_do_not_inherit_memory(memory_api):
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏')
    state(api, sword, '阿宁', number=12, candidate=True)
    outline(api)
    old_lifecycle = snapshot(api)['novel_lifecycle_id']
    api.user.id = 2
    assert api.client.get('/api/novels/1/story-memory').status_code == 404
    response = api.client.post('/api/novels/1/story-memory/entities', json=dict(request_id=str(uuid4()), expected_version=0,
        novel_lifecycle_id=old_lifecycle, name='越权', kind='character'))
    assert response.status_code == 404
    api.user.id = 1
    assert chapters.delete_novel(api.db, 1)
    for model in (StoryEntity, StoryFact, OutlineNode, StateCandidate, StoryMemoryCommand, StoryMemoryHead):
        assert api.db.query(model).filter_by(novel_id=1).count() == 0
    api.db.add(Novel(id=1, title='新生命周期', user_id=1))
    api.db.commit()
    current = snapshot(api)
    assert current['novel_lifecycle_id'] != old_lifecycle and current['states'] == [] and current['version'] == 0
    command(api, '/entities', request=dict(request_id=str(uuid4()), expected_version=0,
        novel_lifecycle_id=old_lifecycle, name='旧命令', kind='character'), status=404)


def test_same_names_have_independent_ids_and_holder_uses_explicit_identity(memory_api):
    """同名医师/木匠保留各自 UUID，物品关联不能按姓名合并。"""
    api = memory_api
    sword = entity(api)
    command(api, '/entities', dict(name='白榆', kind='character', description='女医师'))
    second, _ = command(api, '/entities', dict(name='白榆', kind='character', description='木匠'))
    twins = {row['description']: row['id'] for row in second['entities'] if row['name'] == '白榆'}
    assert len(set(twins.values())) == 2
    command(api, '/states', dict(entity_id=sword, attribute='holder', value='白榆', effective_chapter=3), status=422)
    state(api, sword, '白榆', target=twins['女医师'])
    state(api, sword, '白榆', number=12, target=twins['木匠'])
    assert snapshot(api, chapter=8)['states'][0]['value_entity_id'] == twins['女医师']
    assert snapshot(api, chapter=20)['states'][0]['value_entity_id'] == twins['木匠']


def test_reconfirm_with_new_source_restores_only_explicitly_reviewed_state(memory_api):
    """作者用新出处核对后能解除前置失效阻断，仍保留旧历史与核对理由。"""
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏')
    state(api, sword, '阿宁', number=12)
    chapter = api.db.query(Chapter).filter_by(novel_id=1, chapter_number=3).one()
    chapters.update_chapter(api.db, chapter.id, ChapterUpdate(expected_version=1, content='林夏借得青霜剑。'))
    changed = snapshot(api)
    assert changed['states'] == []
    later = next(row for row in changed['state_history'] if row['chapter_established'] == 12)
    restored, _ = command(api, f"/states/{later['id']}/resolve", dict(source_refs=[source(api, 12)], reason='已核对借剑不影响本次保管'))
    assert [row['id'] for row in restored['states']] == [later['id']]
    assert restored['states'][0]['description'] == '已核对借剑不影响本次保管'


def test_delete_source_preserves_history_and_stale_candidate_cannot_confirm(memory_api):
    api = memory_api
    sword = entity(api)
    state(api, sword, '林夏')
    pending = state(api, sword, '阿宁', number=12, candidate=True)['candidates'][0]
    chapter = api.db.query(Chapter).filter_by(novel_id=1, chapter_number=12).one()
    old_source = source(api, 12)
    chapter_id = chapter.id
    chapters.delete_chapter(api.db, chapter_id)
    command(api, f"/candidates/{pending['id']}/decision", dict(action='confirm'), status=409)
    assert snapshot(api)['candidates'][0]['source_status'] == 'needs_review'
    api.db.add(Chapter(id=chapter_id, novel_id=1, chapter_number=12, title='替代章节', content=old_source['quote']))
    api.db.commit()
    command(api, '/candidates', dict(entity_id=sword, attribute='holder', value='阿宁', effective_chapter=12,
        source_refs=[old_source]), status=404)
    assert len(snapshot(api)['state_history']) == 1
