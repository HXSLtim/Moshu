"""章号认知回归:稿件回执明示真实落点,被拒稿不再污染章号推断。

归一化落点(空白末章填充/新章 max+1)有单一事实源,回给模型的回执与
终局落库共用;历史里被拒绝的稿件正文以墓碑替代,章号认知只认章节表。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import writing_chat
from app.db.base import Base, get_db
from app.models.novel import Chapter, Novel
from app.models.user import User
from app.models.writing_chat import WritingProposal, WritingTurn


class RecordingAgent:
    """按脚本返回流式响应并记录每轮实际收到的消息,便于断言回执内容。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_payloads = []

    def bind_tools(self, tools):
        return self

    async def astream(self, payload):
        self.seen_payloads.append(payload)
        yield self.responses.pop(0)


@pytest.fixture
def cognition_api(monkeypatch):
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
    model = RecordingAgent([])
    monkeypatch.setattr(writing_chat.writing_service, 'llm', model)
    # 域流程断言锁定旧链替身(模型级打桩)；C2 删旧链时随批迁 core 替身。
    from app.core.config import settings as _settings
    monkeypatch.setattr(_settings, 'NAI_AGENT_RUNTIME', 'langgraph')
    with TestClient(app) as client:
        yield client, db, model
    db.close(); engine.dispose()


def _create_manuscript_script(model):
    model.responses = [
        AIMessageChunk(content='', tool_calls=[{'name': 'write_manuscript', 'args': {
            'operation': 'create', 'content': '新章正文。', 'title': '第二章'}, 'id': 'call-1'}]),
        AIMessageChunk(content='写好了。', response_metadata={'finish_reason': 'stop'}),
    ]


def _send_turn(client, current_content):
    response = client.post('/api/writing-chat/1/turns', json={
        'request_id': str(uuid4()), 'chapter_id': 1, 'mode': 'discuss',
        'message': '写下一章', 'current_content': current_content})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_ack_states_next_chapter_when_tail_has_content(cognition_api):
    """末章有内容:create 回执明示「第 2 章的新章」,模型下一轮真实可见。"""
    client, db, model = cognition_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='已有正文'))
    db.commit()
    _create_manuscript_script(model)

    turn = _send_turn(client, '已有正文')
    assert turn['result']['landing'] == '第 2 章的新章'
    second_round = model.seen_payloads[1]
    acks = [message.content for message in second_round if isinstance(message, ToolMessage)]
    assert any('第 2 章的新章' in ack and '采纳前它不是已存在的章' in ack for ack in acks), acks


@pytest.mark.asyncio
async def test_ack_states_blank_tail_fill_when_last_chapter_empty(cognition_api):
    """空白末章:create 归一为填充,回执明示「第 1 章的填充」。"""
    client, db, model = cognition_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content=''))
    db.commit()
    _create_manuscript_script(model)

    turn = _send_turn(client, '')
    assert turn['result']['landing'].startswith('第 1 章的填充')
    second_round = model.seen_payloads[1]
    acks = [message.content for message in second_round if isinstance(message, ToolMessage)]
    assert any('第 1 章的填充' in ack for ack in acks), acks


def test_rejected_draft_tombstoned_in_history(cognition_api):
    """被拒稿件正文换成墓碑;待采纳与已采纳稿件保留落点摘要。"""
    client, db, _model = cognition_api
    novel = db.get(Novel, 1)
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='已有正文'))
    db.commit()

    def seed_turn(proposal_status, landing):
        turn = WritingTurn(novel_id=1, request_id=str(uuid4()), chapter_id=1, chapter_title='第一章',
                           mode='new_chapter', user_text='写第三章', assistant_text='第三章正文草稿全文。',
                           base_content_hash='0' * 64, status='completed',
                           result={'actions': [], 'uncertainties': [], 'decided_mode': 'new_chapter',
                                   'manuscript': {'operation': 'create'}, 'landing': landing},
                           novel_lifecycle_id=novel.rag_lifecycle_id)
        db.add(turn)
        db.flush()
        if proposal_status is not None:
            proposal = WritingProposal(id=str(uuid4()), novel_id=1, actor_id=1,
                novel_lifecycle_id=novel.rag_lifecycle_id, turn_id=turn.id, chapter_id=1,
                base_version=1, base_content_hash='0' * 64, operation='create',
                target_chapter_number=3, content='第三章正文草稿全文。', status=proposal_status)
            db.add(proposal)
            db.flush()
            turn.proposal_id = proposal.id
        return turn

    seed_turn('rejected', '第 3 章的新章')
    seed_turn('pending', '第 3 章的新章')
    seed_turn('accepted', '第 3 章的新章')
    seed_turn(None, '')

    def seed_discussion(assistant_text):
        row = WritingTurn(novel_id=1, request_id=str(uuid4()), chapter_id=1, chapter_title='第一章',
                          mode='discuss', user_text='接下来怎么写', assistant_text=assistant_text,
                          base_content_hash='0' * 64, status='completed',
                          result={'actions': [], 'uncertainties': [], 'decided_mode': 'discuss'},
                          novel_lifecycle_id=novel.rag_lifecycle_id)
        db.add(row)

    seed_discussion('第三章 起扫\n\n' + '内联草稿正文。' * 120)
    seed_discussion('可以走三条线：一是宗门暗流，二是木牌来历，三是白狐身份。')
    db.commit()

    history = writing_chat._recent_history(db, 1)
    assert '已被作者拒绝' in history[0].assistant_text and '第三章正文草稿全文' not in history[0].assistant_text
    assert history[0].actions_note and '已被作者拒绝' in history[0].actions_note
    assert history[1].assistant_text == '第三章正文草稿全文。'
    assert '待作者采纳' in history[1].actions_note
    assert history[2].assistant_text == '第三章正文草稿全文。'
    assert '已采纳' in history[2].actions_note
    assert history[3].actions_note == ''
    # 无稿件的长回复截断并标注为讨论内容,不再以「存在的章」参与章号推断。
    long_reply = history[4].assistant_text
    assert len(long_reply) < 700 and '不构成已有章节' in long_reply and long_reply.startswith('第三章 起扫')
    assert '未登记为候选' in long_reply
    assert history[5].assistant_text == '可以走三条线：一是宗门暗流，二是木牌来历，三是白狐身份。'


def test_prompt_contract_forbids_inline_manuscript():
    """契约守卫:正文唯一通道、章号纪律与意图映射必须同时在场,防止提示词回退。"""
    assert '只有一个交付通道' in writing_chat.AGENT_SYSTEM_PROMPT
    assert '只认系统提供的当前正文和稿件回执' in writing_chat.AGENT_SYSTEM_PROMPT
    assert '「写下一章／开新章」对应 operation=create' in writing_chat.AGENT_SYSTEM_PROMPT
    from app.services.conversation.runtime import PROPOSE_TOOLS
    spec = next(item for item in PROPOSE_TOOLS if item['function']['name'] == 'write_manuscript')
    assert '唯一交付通道' in spec['function']['description']


@pytest.mark.asyncio
async def test_chapter_anchor_injected_before_drafting(cognition_api):
    """起草可见的系统上下文含权威章数:历史幻觉(被拒的第三章)带不偏锚点。"""
    client, db, model = cognition_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content='已有正文'))
    novel = db.get(Novel, 1)
    rejected = WritingTurn(novel_id=1, request_id=str(uuid4()), chapter_id=1, chapter_title='第一章',
                           mode='new_chapter', user_text='写第三章', assistant_text='第三章正文草稿全文。',
                           base_content_hash='0' * 64, status='completed',
                           result={'actions': [], 'uncertainties': [], 'decided_mode': 'new_chapter',
                                   'manuscript': {'operation': 'create'}, 'landing': '第 3 章的新章'},
                           novel_lifecycle_id=novel.rag_lifecycle_id)
    db.add(rejected); db.flush()
    proposal = WritingProposal(id=str(uuid4()), novel_id=1, actor_id=1, novel_lifecycle_id=novel.rag_lifecycle_id,
                               turn_id=rejected.id, chapter_id=1, base_version=1, base_content_hash='0' * 64,
                               operation='create', target_chapter_number=3, content='第三章正文草稿全文。',
                               status='rejected')
    db.add(proposal); db.flush()
    rejected.proposal_id = proposal.id
    db.commit()

    model.responses = [AIMessageChunk(content='我先看看现有设定。', response_metadata={'finish_reason': 'stop'})]
    _send_turn(client, '已有正文')
    system = model.seen_payloads[0][0].content
    assert '【章节真值】' in system and '现有 1 章' in system and '新建第 2 章' in system
    assert '不是已存在的章' in system


@pytest.mark.asyncio
async def test_chapter_anchor_blank_tail_states_fill(cognition_api):
    """空白末章时锚点明示填充语义,与归一器口径一致。"""
    client, db, model = cognition_api
    db.add(Chapter(id=1, novel_id=1, chapter_number=1, title='第一章', content=''))
    db.commit()
    model.responses = [AIMessageChunk(content='好的。', response_metadata={'finish_reason': 'stop'})]
    _send_turn(client, '')
    system = model.seen_payloads[0][0].content
    assert '现有 1 章' in system and '填充第 1 章' in system


@pytest.mark.asyncio
async def test_new_chapter_task_anchors_landing_number():
    """new_chapter 显式任务路径:系统描述锚定权威落点章号。"""
    from unittest.mock import AsyncMock
    from app.services.conversation.tasks import TaskOptions, execute_task
    captured = []

    async def ainvoke(messages):
        captured.append(messages)
        return SimpleNamespace(content='{"title":"石阶尽头","content":"正文。"}')

    service = SimpleNamespace(prepare_messages=lambda **_: [('system', '共享上下文')],
                               llm=SimpleNamespace(ainvoke=ainvoke))
    result = await execute_task(mode='new_chapter', service=service, context_pack=SimpleNamespace(),
                                current_content='前文。', instruction='写下一章', history=[],
                                options=TaskOptions(target_length=800), novel_id=1, actor_id=1,
                                novel_lifecycle_id='a' * 32, target_chapter=7)
    assert '本章是全书第 7 章' in captured[0][0][1]
    assert result.operation == 'create'
