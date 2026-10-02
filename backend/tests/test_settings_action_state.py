"""设定提案决策持久化与重复应用幂等回归。

设定提案不走 WritingProposal 表,决策位落在轮次结果里,刷新后卡片按
终态渲染;applied 由服务端恰一次执行写入(命令层确定性请求标识+事实
全键去重),卡片复活或换请求标识重放都不产生重复行。名字和标题不是
身份,CRUD 层不做同名去重(同名实体各有独立 ID 是既有不变量)。
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import writing_chat
from app.crud import story_bible as story_bible_crud
from app.db.base import Base, get_db
from app.models.novel import Chapter, Novel
from app.models.story_bible import StoryFact
from app.models.story_bible_schemas import FactCreate
from app.models.story_memory import OutlineNode, StoryEntity, StoryMemoryCommand
from app.models.user import User
from app.models.writing_chat import WritingTurn


@pytest.fixture
def state_api():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add(User(id=1, username='author', email='author@example.com', hashed_password='unused'))
    db.add(Novel(id=1, user_id=1, title='青州夜行'))
    db.commit()
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='原稿'))
    db.commit()
    app = FastAPI()
    app.include_router(writing_chat.router, prefix='/api/writing-chat')

    def get_test_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client, db
    db.close(); engine.dispose()


def _completed_turn(db, novel, actions):
    row = WritingTurn(novel_id=novel.id, request_id=str(uuid4()), chapter_id=1,
                      chapter_title='第一章', mode='discuss', user_text='记一下设定',
                      assistant_text='已整理。', base_content_hash='0' * 64, status='completed',
                      result={'actions': actions, 'uncertainties': [], 'decided_mode': 'discuss'},
                      novel_lifecycle_id=novel.rag_lifecycle_id)
    db.add(row)
    db.commit()
    return row


def _decide(client, turn_id, decision, indexes=None):
    return client.post(f'/api/writing-chat/1/turns/{turn_id}/actions/decision', json={
        'request_id': str(uuid4()), 'decision': decision,
        **({'indexes': indexes} if indexes is not None else {})})


def test_action_decision_persists_and_survives_reload(state_api):
    """决策写入轮次结果后,重新读取历史仍能看到终态;重复提交幂等。"""
    client, db = state_api
    novel = db.get(Novel, 1)
    turn = _completed_turn(db, novel, [
        {'kind': 'entity', 'name': '林夏', 'entity_kind': 'character', 'description': '主角'},
        {'kind': 'fact', 'subject': '林夏', 'attribute': '身份', 'value': '剑修'},
    ])

    assert _decide(client, turn.id, 'applied').status_code == 200
    first = client.get('/api/writing-chat/1/turns').json()[0]
    assert [action['decision'] for action in first['result']['actions']] == ['applied', 'applied']
    decided_at = first['result']['actions'][0]['decided_at']
    assert decided_at

    # 卡片复活场景:同一决策再提交一次,幂等返回且不刷新原决策时间。
    assert _decide(client, turn.id, 'applied').status_code == 200
    again = client.get('/api/writing-chat/1/turns').json()[0]
    assert again['result']['actions'][0]['decided_at'] == decided_at

    # 已写入是终态:不能改口为跳过。
    assert _decide(client, turn.id, 'skipped').status_code == 409


def test_skipped_action_can_still_be_applied_later(state_api):
    """「先不写入」不是终态:作者改主意后仍可补登为已写入。"""
    client, db = state_api
    novel = db.get(Novel, 1)
    turn = _completed_turn(db, novel, [{'kind': 'entity', 'name': '阿宁', 'entity_kind': 'character'}])

    assert _decide(client, turn.id, 'skipped').status_code == 200
    assert _decide(client, turn.id, 'applied').status_code == 200
    history = client.get('/api/writing-chat/1/turns').json()[0]
    assert history['result']['actions'][0]['decision'] == 'applied'


def test_decision_validates_scope_and_bad_indexes(state_api):
    """未完成轮次与越界序号拒绝登记;他人小说不可见。"""
    client, db = state_api
    novel = db.get(Novel, 1)
    failed = WritingTurn(novel_id=novel.id, request_id=str(uuid4()), chapter_id=1,
                         chapter_title='第一章', mode='discuss', user_text='x', assistant_text='',
                         base_content_hash='0' * 64, status='failed', error='失败',
                         novel_lifecycle_id=novel.rag_lifecycle_id)
    db.add(failed); db.commit()
    assert _decide(client, failed.id, 'applied').status_code == 409

    turn = _completed_turn(db, novel, [{'kind': 'fact', 'subject': 's', 'attribute': 'a', 'value': 'v'}])
    assert _decide(client, turn.id, 'applied', indexes=[5]).status_code == 422
    assert _decide(client, turn.id, 'applied', indexes=[0]).status_code == 200


def test_repeat_apply_through_decision_creates_no_duplicate_rows(state_api):
    """卡片复活场景:同一轮 applied 决策重复提交,四类写入都零新增行。"""
    client, db = state_api
    novel = db.get(Novel, 1)
    turn = _completed_turn(db, novel, [
        {'kind': 'project_info', 'genre': '仙侠', 'description': '少年持剑'},
        {'kind': 'entity', 'name': '林夏', 'entity_kind': 'character', 'description': '主角'},
        {'kind': 'outline', 'node_kind': 'chapter', 'title': '初入宗门', 'chapter_number': 2,
         'summary': '林夏拜入青云宗'},
        {'kind': 'fact', 'subject': '林夏', 'attribute': '身份', 'value': '剑修'},
    ])

    assert _decide(client, turn.id, 'applied').status_code == 200
    db.expire_all()
    assert db.query(StoryEntity).count() == 1
    assert db.query(OutlineNode).count() == 1
    assert db.query(StoryFact).count() == 1
    assert db.get(Novel, 1).genre == '仙侠'

    # 卡片复活再点一次:决策已持久为 applied,不重复执行。
    assert _decide(client, turn.id, 'applied').status_code == 200
    db.expire_all()
    assert db.query(StoryEntity).count() == 1
    assert db.query(OutlineNode).count() == 1
    assert db.query(StoryFact).count() == 1

    # 标记丢失的极端场景(直接抹掉决策位模拟):命令层确定性请求标识兜底,
    # 重放仍不产生重复行。抹标记须走副本重赋值,原地改写不会被持久化。
    fresh = db.query(WritingTurn).filter_by(id=turn.id).first()
    stripped = []
    for position, item in enumerate(fresh.result['actions']):
        copy = dict(item)
        if position:
            copy.pop('decision', None)
            copy.pop('decided_at', None)
        stripped.append(copy)
    fresh.result = {**fresh.result, 'actions': stripped}
    db.commit()
    assert _decide(client, turn.id, 'applied').status_code == 200
    db.expire_all()
    assert db.query(StoryEntity).count() == 1
    assert db.query(OutlineNode).count() == 1
    assert db.query(StoryFact).count() == 1
    assert db.query(StoryMemoryCommand).count() == 2, '实体与大纲各一条命令,重放未新增'


def test_fact_crud_full_key_dedupe_keeps_supersession_path(state_api):
    """事实 CRUD 全键去重:同键同值返回已有行;取值变化照常新建,交由作者退役更替。"""
    client, db = state_api
    novel = db.get(Novel, 1)
    first = story_bible_crud.create_fact(db, FactCreate(
        novel_id=novel.id, subject='林夏', attribute='身份', value='剑修'), commit=False)
    second = story_bible_crud.create_fact(db, FactCreate(
        novel_id=novel.id, subject='林夏', attribute='身份', value='剑修'), commit=False)
    assert first.id == second.id
    assert db.query(StoryFact).count() == 1
    story_bible_crud.create_fact(db, FactCreate(
        novel_id=novel.id, subject='林夏', attribute='身份', value='剑宗内门'), commit=False)
    assert db.query(StoryFact).count() == 2
