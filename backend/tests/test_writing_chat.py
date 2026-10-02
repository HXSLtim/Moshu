"""持久对话、历史上下文、权限与候选隔离。"""
import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.api.routes import writing_chat
from app.db.base import Base, get_db
from app.models.novel import Novel, Chapter
from app.models.user import User
from tests.agent_stub import AgentStub
from app.models.writing_chat import WritingTurn
from app.services.context.budget import build_writing_chat_messages, MAX_CHAT_HISTORY_CHARS


@pytest.fixture
def chat_api(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    db = sessions()
    author = User(id=1, username='author', email='author@example.com', hashed_password='unused')
    other = User(id=2, username='other', email='other@example.com', hashed_password='unused')
    db.add_all([author, other]); db.commit()
    db.add_all([Novel(id=1, user_id=1, title='青州夜行', worldview='钟声报时'), Novel(id=2, user_id=2, title='他人作品')]); db.commit()
    db.add_all([Chapter(id=1, novel_id=1, title='第一章', chapter_number=1, content='已保存原稿'),
                Chapter(id=2, novel_id=2, title='他人章节', chapter_number=1, content='私密正文')]); db.commit()
    app = FastAPI()
    app.include_router(writing_chat.router, prefix='/api/writing-chat')
    def get_test_db():
        session = sessions()
        try: yield session
        finally: session.close()
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: author
    model = AsyncMock(return_value=SimpleNamespace(content='这枚玉佩可以成为下一幕的线索。'))
    monkeypatch.setattr(writing_chat.writing_service, 'llm', AgentStub(model))
    with TestClient(app) as client:
        yield client, db, model
    db.close(); engine.dispose()


def payload(**kwargs):
    return {'request_id': str(uuid4()), 'chapter_id': 1, 'message': '主角为什么要隐瞒身份？',
            'mode': 'discuss', 'current_content': '最新未保存原稿', **kwargs}


def test_history_survives_new_requests_and_enters_next_context(chat_api):
    """记录在数据库中恢复，下一轮模型真实接收上轮问答。"""
    client, db, model = chat_api
    first = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert first['status'] == 'completed'
    second = client.post('/api/writing-chat/1/turns', json=payload(message='把你刚才说的线索展开')).json()
    assert second['id'] > first['id']
    history = client.get('/api/writing-chat/1/turns').json()
    assert len(history) == 2 and history[0]['assistant_text'] == first['assistant_text']
    sent = model.call_args.args[0]
    assert any(getattr(message, 'content', None) == first['assistant_text']
               or message == ('ai', first['assistant_text']) for message in sent)
    assert any('主角为什么要隐瞒身份' in (message.content if hasattr(message, 'content') else message[1])
               for message in sent)
    assert '最新未保存原稿' in (sent[0].content if hasattr(sent[0], 'content') else sent[0][1])
    assert db.get(Chapter, 1).content == '已保存原稿'


def test_duplicate_request_is_idempotent_and_candidate_stays_separate(chat_api):
    """重复发送同一请求不重复计费，续写候选不自动写入正文。"""
    client, db, model = chat_api
    data = payload(mode='continue')
    first = client.post('/api/writing-chat/1/turns', json=data).json()
    second = client.post('/api/writing-chat/1/turns', json=data).json()
    assert first['id'] == second['id']
    assert len(first['base_content_hash']) == 64
    assert model.call_count == 1
    assert db.get(Chapter, 1).content == '已保存原稿'


def test_owner_and_chapter_isolation(chat_api):
    """不能读他人历史、向他人小说发消息或引用他人章节。"""
    client, _, model = chat_api
    assert client.get('/api/writing-chat/2/turns').status_code == 404
    assert client.post('/api/writing-chat/2/turns', json=payload()).status_code == 404
    assert client.post('/api/writing-chat/1/turns', json=payload(chapter_id=2)).status_code == 404
    assert client.post(f'/api/writing-chat/2/turns/{uuid4()}/stop').status_code == 404
    assert model.call_count == 0


def test_model_failure_keeps_question_without_leaking_provider_error(chat_api):
    """连接失败保留问题并明确标记，不能泄露上游错误中的配置。"""
    client, _, model = chat_api
    model.side_effect = RuntimeError('secret-provider-error')
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'failed'
    assert result['user_text'] == '主角为什么要隐瞒身份？'
    assert 'secret-provider-error' not in result['error']
    assert client.get('/api/writing-chat/1/turns').json()[0]['status'] == 'failed'


def test_stopped_turn_ignores_late_model_reply(chat_api):
    """停止状态不能被迟到的模型结果重新标记为成功。"""
    client, db, model = chat_api
    async def complete_after_stop(*_args):
        db.query(WritingTurn).update({'status': 'cancelled', 'error': '已停止生成'})
        db.commit()
        return SimpleNamespace(content='迟到回复')
    model.side_effect = complete_after_stop
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'cancelled' and result['assistant_text'] == ''


def test_history_pagination_and_novel_deletion(chat_api):
    """历史按稳定 ID 翻页，删除小说时同步删除对话。"""
    client, db, _ = chat_api
    for i in range(35):
        db.add(WritingTurn(novel_id=1, request_id=str(uuid4()), chapter_id=1, chapter_title='第一章', mode='discuss',
                           user_text=f'问题{i}', assistant_text='回答', status='completed', base_content_hash='0'*64))
    db.commit()
    newest = client.get('/api/writing-chat/1/turns').json()
    assert len(newest) == 30
    older = client.get(f"/api/writing-chat/1/turns?before={newest[0]['id']}").json()
    assert len(older) == 5 and older[-1]['id'] < newest[0]['id']
    db.delete(db.get(Novel, 1)); db.commit()
    assert db.query(WritingTurn).count() == 0


def test_dialogue_budget_preserves_latest_instruction():
    """长对话限制历史预算，同时完整保留本轮指令。"""
    turns = [SimpleNamespace(chapter_title='第一章', user_text='问'*4000, assistant_text='答'*20000) for _ in range(20)]
    messages = build_writing_chat_messages(worldview='设定'*5000, current_content='正文'*50000,
        story_context='事实'*5000, turns=turns, instruction='保留本轮完整要求', mode='discuss')
    assert messages[-1] == ('human', '保留本轮完整要求')
    assert sum(len(message) for _, message in messages[1:-1]) <= MAX_CHAT_HISTORY_CHARS
    assert len(messages[0][1]) < 5000


def test_empty_message_is_rejected(chat_api):
    client, _, model = chat_api
    assert client.post('/api/writing-chat/1/turns', json=payload(message='   ')).status_code == 422
    assert model.call_count == 0


def test_stop_and_recover_abandoned_turns(chat_api):
    """停止接口写入终态；服务重启遗留的旧请求在读取时恢复为失败。"""
    from datetime import datetime, timedelta
    client, db, _ = chat_api
    live_id, abandoned_id = str(uuid4()), str(uuid4())
    for request_id, created in [(live_id, datetime.utcnow()), (abandoned_id, datetime.utcnow() - timedelta(days=1))]:
        db.add(WritingTurn(novel_id=1, request_id=request_id, chapter_id=1, chapter_title='第一章', mode='discuss',
                           user_text='等待回复的问题', base_content_hash='0'*64, status='pending', created_at=created))
    db.commit()
    stopped = client.post(f'/api/writing-chat/1/turns/{live_id}/stop').json()
    assert stopped['status'] == 'cancelled'
    recovered = {item['request_id']: item for item in client.get('/api/writing-chat/1/turns').json()}
    assert recovered[abandoned_id]['status'] == 'failed'
    assert recovered[live_id]['status'] == 'cancelled'


def test_stop_does_not_overwrite_completion_after_read(chat_api):
    """停止请求读到旧 pending 快照时，不得覆盖执行器刚写入的完成状态。"""
    client, db, _ = chat_api
    request_id = str(uuid4())
    db.add(WritingTurn(novel_id=1, request_id=request_id, chapter_id=1, chapter_title='第一章',
                       mode='discuss', user_text='问题', base_content_hash='0'*64, status='pending'))
    db.commit()

    def finish_after_snapshot(turn, context):
        if turn.request_id == request_id:
            # 在 ORM 已取得 pending 快照后改变数据库状态，制造迟到取消的确定性窗口。
            context.session.connection().execute(update(WritingTurn).where(WritingTurn.id == turn.id).values(
                status='completed', assistant_text='已完成回复', error=None,
            ))

    event.listen(WritingTurn, 'load', finish_after_snapshot)
    try:
        result = client.post(f'/api/writing-chat/1/turns/{request_id}/stop')
    finally:
        event.remove(WritingTurn, 'load', finish_after_snapshot)
    assert result.status_code == 200
    assert result.json()['status'] == 'completed'
    assert result.json()['assistant_text'] == '已完成回复'
    assert result.json()['error'] is None


@pytest.mark.parametrize(('response', 'error_fragment'), [
    (SimpleNamespace(content='半段正文', response_metadata={'finish_reason': 'length'}), '截断'),
    (SimpleNamespace(content='被过滤的正文', response_metadata={'finish_reason': 'content_filter'}), '完整回复'),
    (SimpleNamespace(content=['文本块']), '不是文本'),
])
def test_incomplete_reply_never_becomes_adoptable_or_enters_history_context(chat_api, response, error_fragment):
    """不完整回复保留为失败轮次，既不产生候选，也不污染下次上下文。"""
    client, db, model = chat_api
    model.return_value = response
    failed = client.post('/api/writing-chat/1/turns', json=payload(mode='continue')).json()
    assert failed['status'] == 'failed'
    assert failed['assistant_text'] == ''
    assert error_fragment in failed['error']
    model.return_value = SimpleNamespace(content='完整的新回复')
    completed = client.post('/api/writing-chat/1/turns', json=payload(message='重新续写')).json()
    assert completed['status'] == 'completed'
    assert all('主角为什么要隐瞒身份' not in message.content
               for message in model.await_args.args[0])
    assert db.get(Chapter, 1).content == '已保存原稿'


def test_timeout_is_distinct_from_provider_connection_failure(chat_api):
    """作者看到明确超时原因，仍可通过原历史恢复失败问题。"""
    import asyncio
    client, _, model = chat_api
    model.side_effect = asyncio.TimeoutError()
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'failed'
    assert '超时' in result['error']


def test_cancelled_turn_ignores_late_truncated_result(chat_api):
    """取消后的输出验证失败不能反向覆盖取消终态。"""
    client, db, model = chat_api
    async def truncate_after_stop(*_args):
        db.query(WritingTurn).update({'status': 'cancelled', 'error': '已停止生成'})
        db.commit()
        return SimpleNamespace(content='半段回复', response_metadata={'finish_reason': 'length'})
    model.side_effect = truncate_after_stop
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'cancelled'
    assert result['error'] == '已停止生成'
    assert result['assistant_text'] == ''


def test_stream_done_event_carries_usage_without_page_refresh(chat_api):
    """流式生成完即回推本轮来源与真实用量，不必刷新页面再走 GET /turns。"""
    client, db, model = chat_api
    with client.stream('POST', '/api/writing-chat/1/turns/stream', json=payload()) as response:
        assert response.status_code == 200
        body = ''.join(response.iter_text())

    events = [json.loads(line[len('data: '):]) for line in body.splitlines() if line.startswith('data: ')]
    done = [event for event in events if event['type'] == 'done']
    assert len(done) == 1
    turn = done[0]['data']['turn']
    assert turn['status'] == 'completed'
    # 字段必须与 TurnResponse 对齐，否则作者要刷新才看得到来源与用量。
    assert set(turn) >= {'status', 'assistant_text', 'context_manifest', 'execution', 'proposal_id'}
    assert turn['context_manifest'] is not None

    # 用量必须来自提供方真实返回；测试替身不带 usage_metadata，因此这里是 null，
    # 但不能因为缺失就省略字段——前端要区分"没有记录"与"提供方未返回"。
    assert 'execution' in turn
    saved = db.query(WritingTurn).filter_by(novel_id=1).first()
    assert saved is not None and saved.execution is not None
    assert saved.execution['status'] == 'completed'
    assert saved.execution['model_calls'] >= 1
    assert saved.execution['usage'] is None
    # 流式轮次的 execution 必须落库，而不是只在响应里出现。
    assert turn['execution']['execution_id'] == saved.execution['execution_id']


def test_previous_actions_note_enters_next_context(chat_api):
    """上轮登记的提案与不确定点进入下一轮上下文，Agent 不重复登记。"""
    client, db, model = chat_api
    db.add(WritingTurn(novel_id=1, chapter_id=1, chapter_title='第一章', mode='discuss',
                       request_id=str(uuid4()), user_text='给主角配一把佩剑',
                       assistant_text='我提议登记实体：青霜剑。',
                       base_content_hash='0' * 64, status='completed',
                       result={'actions': [{'kind': 'entity', 'name': '青霜剑',
                                            'entity_kind': 'item', 'description': '佩剑'}],
                               'uncertainties': ['剑的来历未确认'], 'decided_mode': 'discuss'}))
    db.commit()
    second = client.post('/api/writing-chat/1/turns', json=payload(message='继续聊这把剑')).json()
    assert second['status'] == 'completed'
    sent = model.call_args.args[0]
    joined = ' '.join(message.content if hasattr(message, 'content') else str(message)
                      for message in sent)
    assert '上轮已登记提案' in joined and '青霜剑' in joined
    assert '未确认点:剑的来历未确认' in joined
