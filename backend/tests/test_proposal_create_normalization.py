"""create 稿件的落库归一化与位置基线回归。

对话在 discuss 轮里由 Agent 决定开新章时,上下文 manifest 的目标章是当前章,
不是创作落章位置;位置基线必须取创建时点的 max+1。末章空白时,作者要的
「下一章」就是填上这个空白章,稿件归一为改写本章,卡片才显示「采纳到本章」。
"""
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import writing_chat
from app.db.base import Base, get_db
from app.models.novel import Chapter, Novel
from app.models.user import User
from app.models.writing_chat import WritingAdoption, WritingProposal


class ScriptedAgent:
    """按脚本依次返回流式响应、保留 tool_calls 字段的模型替身。

    AgentStub.astream 会重建不带工具调用的消息块,无法驱动稿件工具路径,
    这里沿用 tests/test_agent_tools.py 中 ScriptedLLM 的最小契约。
    """

    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    async def astream(self, payload):
        yield self.responses.pop(0)


@pytest.fixture
def normalize_api(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add(User(id=1, username='author', email='author@example.com', hashed_password='unused'))
    db.add(Novel(id=1, user_id=1, title='青州夜行'))
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
    model = ScriptedAgent([])
    monkeypatch.setattr(writing_chat.writing_service, 'llm', model)
    with TestClient(app) as client:
        yield client, db, model
    db.close(); engine.dispose()


def _agent_new_chapter_script(model):
    """模型替身脚本:先提交 create 稿件工具调用,再给出收尾答复。"""
    model.responses = [
        AIMessageChunk(content='', tool_calls=[{'name': 'write_manuscript', 'args': {
            'operation': 'create', 'content': '新章正文:灯下的人推开了门。', 'title': '第二章 灯下'}, 'id': 'call-1'}]),
        AIMessageChunk(content='新章已经写好,请查收候选。', response_metadata={'finish_reason': 'stop'}),
    ]


def _send_create_turn(client, current_content):
    response = client.post('/api/writing-chat/1/turns', json={
        'request_id': str(uuid4()), 'chapter_id': 1, 'mode': 'discuss',
        'message': '接着写下一章', 'current_content': current_content})
    assert response.status_code == 200, response.text
    return response.json()


def _accept(client, proposal_id, expected_version, expected_content_hash):
    return client.post(f'/api/writing-chat/1/proposals/{proposal_id}/accept', json={
        'request_id': str(uuid4()), 'expected_version': expected_version,
        'expected_content_hash': expected_content_hash})


def test_blank_last_chapter_create_normalizes_to_replace(normalize_api):
    """末章空白时 create 归一为改写本章:基线哈希按空白正文算,采纳不再 409。"""
    client, db, model = normalize_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content=''))
    db.commit()
    _agent_new_chapter_script(model)

    turn = _send_create_turn(client, '')
    assert turn['mode'] == 'rewrite', '归一后卡片语义应为改写本章'
    proposal = db.query(WritingProposal).one()
    assert proposal.operation == 'replace'
    assert proposal.chapter_id == 1
    assert proposal.target_chapter_number is None
    assert proposal.base_content_hash == sha256(b'').hexdigest()

    accepted = _accept(client, turn['proposal_id'], proposal.base_version, proposal.base_content_hash)
    assert accepted.status_code == 200, accepted.text
    db.expire_all()
    chapter = db.get(Chapter, 1)
    assert chapter.content == '新章正文:灯下的人推开了门。'
    assert chapter.version == 2, '空白章被改写而不是新建章节'
    assert db.query(Chapter).count() == 1


def test_whitespace_only_last_chapter_still_counts_blank(normalize_api):
    """空白判定按非空白字符数:只有空格换行的末章同样归一为改写。"""
    client, db, model = normalize_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content=' \n　 '))
    db.commit()
    _agent_new_chapter_script(model)

    turn = _send_create_turn(client, ' \n　 ')
    proposal = db.query(WritingProposal).one()
    assert proposal.operation == 'replace'


def test_contentful_last_chapter_create_targets_next_position(normalize_api):
    """末章有内容时保持 create:基线取创建时点 max+1,不信任上下文 manifest。"""
    client, db, model = normalize_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='已保存的原稿。'))
    db.commit()
    _agent_new_chapter_script(model)

    turn = _send_create_turn(client, '已保存的原稿。')
    assert turn['mode'] == 'new_chapter'
    proposal = db.query(WritingProposal).one()
    assert proposal.operation == 'create'
    assert proposal.target_chapter_number == 2
    # discuss 轮的上下文目标章是当前章;位置基线不得取该值(原死锁根因)。
    assert turn['context_manifest']['scope']['target_chapter'] == 1

    accepted = _accept(client, turn['proposal_id'], proposal.base_version, proposal.base_content_hash)
    assert accepted.status_code == 200, accepted.text
    db.expire_all()
    assert db.get(Chapter, 1).content == '已保存的原稿。'
    created = db.query(Chapter).filter_by(chapter_number=2).one()
    assert created.content == '新章正文:灯下的人推开了门。'
    assert created.title == '第二章 灯下'


def test_few_words_last_chapter_is_not_blank(normalize_api):
    """末章哪怕只有一个字也是作者真实内容:create 不得覆盖,仍走新章。"""
    client, db, model = normalize_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='好'))
    db.commit()
    _agent_new_chapter_script(model)

    _send_create_turn(client, '好')
    proposal = db.query(WritingProposal).one()
    assert proposal.operation == 'create'
    assert proposal.target_chapter_number == 2


def test_auto_apply_adopts_normalized_blank_chapter(normalize_api):
    """none 档自动采纳走归一化路径:空白末章直接填上,不再因基线问题静默留 pending。"""
    client, db, model = normalize_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content=''))
    db.query(Novel).update({'review_mode': 'none'})
    db.commit()
    _agent_new_chapter_script(model)

    _send_create_turn(client, '')
    db.expire_all()
    proposal = db.query(WritingProposal).one()
    assert proposal.status == 'accepted', '自动采纳应成功,不得静默留 pending'
    chapter = db.get(Chapter, 1)
    assert chapter.content == '新章正文:灯下的人推开了门。'
    assert db.query(Chapter).count() == 1
    audit = db.query(WritingAdoption).one()
    assert audit.request_id == f'auto:{proposal.id}'
