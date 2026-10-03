"""Core Agent P4 双轨接线测试：灰度开关、core 消息形状、execution 载荷兼容
与端到端事件序(「前端零改动」验收线在真实路由层的锁定)。
"""
import json

import pytest

from app.api.routes import writing_chat
from app.services.conversation.core.budget import CoreBudget
from app.services.conversation.core.types import ModelResponse
from tests.test_writing_chat import chat_api, payload  # 复用隔离夹具与载荷


def test_core_agent_messages_shape(chat_api, monkeypatch):
    client, db, _model = chat_api
    from app.models.novel import Novel, Chapter
    novel = db.query(Novel).get(1)
    chapter = db.query(Chapter).filter_by(novel_id=1).first()

    class _Data:
        current_content = '正文'
        message = '接着写'

    messages = writing_chat._core_agent_messages(
        SimpleContextPack(), _Data(), novel, [], db, chapter)
    assert messages[0]['role'] == 'system'
    assert '创作 Agent' in messages[0]['content']  # 系统契约在位
    assert all(isinstance(m, dict) and {'role', 'content'} <= set(m) for m in messages)
    assert messages[-1]['role'] == 'user' and messages[-1]['content'] == '接着写'


class SimpleContextPack:
    worldview = '钟声报时'
    story_bible_context = []
    digest_context = ''
    structured_context = ''


def test_core_execution_payload_keyface_matches_legacy_meter():
    budget = CoreBudget(max_model_calls=20)
    budget.record_call({'input': 10, 'output': 5, 'total': 15})
    payload = writing_chat._core_execution_payload(budget, 1, 0.0)
    # 与旧 execution.py snapshot 的键面逐一兼容(前端用量渲染零改动)。
    assert set(payload) >= {'execution_id', 'status', 'model_calls', 'max_model_calls',
                            'latency_ms', 'usage', 'calls', 'error_code', 'transport_attempts',
                            'deadline_seconds'}
    assert payload['model_calls'] == 1
    assert payload['usage']['total_tokens'] == 15


class _ScriptedCoreProvider:
    """core 端到端的假 provider：一段文本回复即收尾。"""

    async def stream(self, messages, tools=None):
        yield {'type': 'text_delta', 'delta': '好的，这一段这样接。'}
        yield {'type': 'response_done', 'response': ModelResponse(
            stop_reason='stop', text='好的，这一段这样接。',
            usage={'input': 120, 'output': 30, 'total': 150})}


def test_stream_endpoint_core_runtime_event_sequence(chat_api, monkeypatch):
    """core 唯一路径下端到端：SSE 帧序与旧链一致，execution 载荷兼容。"""
    client, db, _model = chat_api
    monkeypatch.setattr(writing_chat, 'OpenAIStreamProvider', lambda: _ScriptedCoreProvider())

    with client.stream('POST', '/api/writing-chat/1/turns/stream', json=payload()) as response:
        assert response.status_code == 200
        body = ''.join(response.iter_text())

    events = [json.loads(line[len('data: '):]) for line in body.splitlines()
              if line.startswith('data: ')]
    kinds = [event['type'] for event in events]
    assert kinds[0] == 'metadata'
    assert kinds[-1] == 'done'
    assert 'chunk' in kinds and 'error' not in kinds
    chunks = [event for event in events if event['type'] == 'chunk']
    assert ''.join(chunk['content'] for chunk in chunks) == '好的，这一段这样接。'
    done = events[-1]
    execution = (done['data']['turn'] or {}).get('execution') or {}
    assert execution.get('model_calls') == 1
    assert (execution.get('usage') or {}).get('total_tokens') == 150
