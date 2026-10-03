"""持久对话使用有效 L1，来源清单固定于生成时刻。"""
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text

from app.crud import novel as novel_crud
from app.models.memory import ChapterDigest, ChapterRevision
from app.models.novel import Chapter
from app.models.schemas import ChapterCreate, ChapterUpdate
from app.models.writing_chat import WritingTurn
from app.services.memory.config import digest_recipe_version
from tests.test_writing_chat import chat_api, payload  # noqa: F401


def seed_previous_digest(db):
    """把原有编辑章移至第3章，为真实前章创建持久版本与带出处简介。"""
    db.get(Chapter, 1).chapter_number = 3
    db.commit()
    chapter = novel_crud.create_chapter(db, 1, ChapterCreate(
        chapter_number=1, title='剑的来处', content='林夏从旧仓库拿到青霜剑，约定只借三日。',
    ))
    revision = db.query(ChapterRevision).filter_by(chapter_id=chapter.id).one()
    quote = chapter.content
    digest = ChapterDigest(
        novel_id=1, chapter_id=chapter.id, source_revision_id=revision.id,
        recipe_version=digest_recipe_version(), summary='林夏借到青霜剑，约定三日归还。',
        participants=['林夏'], events=['借剑'], state_change_candidates=['危险候选：青霜剑永久归林夏所有'],
        open_threads=['危险未来：林夏将在结局杀死同伴'],
        source_refs=[{'revision_id': revision.id, 'start': 0, 'end': len(quote), 'quote': quote,
                      'content_hash': revision.content_hash,
                      'quote_hash': hashlib.sha256(quote.encode()).hexdigest()}],
    )
    db.add(digest); db.commit()
    return chapter, revision, digest


def _first_content(payload):
    """取首条消息文本；Agent 路径(core)给 OpenAI dict，其余路径给 (role, text)。"""
    first = payload[0]
    return first['content'] if isinstance(first, dict) else (first.content if hasattr(first, 'content') else first[1])


def test_chat_recall_reaches_real_messages_and_manifest_survives_history(chat_api):
    """从数据库读取的简介进入真实消息；历史恢复仍显示当时固定来源。"""
    client, db, model = chat_api
    chapter, revision, digest = seed_previous_digest(db)
    data = payload(mode='continue')
    first = client.post('/api/writing-chat/1/turns', json=data).json()
    assert first['status'] == 'completed'
    system = _first_content(model.await_args.args[0])  # mode=continue 走固定任务链
    assert digest.summary in system
    assert '自动提取' in system
    assert '危险候选' not in system and '危险未来' not in system
    assert '最新未保存原稿' in system
    manifest = first['context_manifest']
    assert manifest['sources'][0]['source_revision_id'] == revision.id
    assert manifest['sources'][0]['source_version'] == 1
    assert manifest['scope']['target_chapter'] == 3
    novel_crud.update_chapter(db, chapter.id, ChapterUpdate(expected_version=1, content='青霜剑从未借出。'))
    again = client.post('/api/writing-chat/1/turns', json=data).json()
    assert again['id'] == first['id'] and model.await_count == 1
    assert again['context_manifest'] == manifest
    history = client.get('/api/writing-chat/1/turns').json()
    assert history[0]['context_manifest'] == manifest
    next_turn = client.post('/api/writing-chat/1/turns', json=payload(message='只按目前原文继续')).json()
    assert next_turn['context_manifest']['sources'] == []
    assert digest.summary not in _first_content(model.core.calls[-1])


def test_failed_turn_keeps_context_manifest_without_adoptable_text(chat_api):
    """模型失败仍可核对本轮参考，且不会产生可采纳正文。"""
    client, db, model = chat_api
    _, revision, _ = seed_previous_digest(db)
    from app.services.conversation.core.types import ModelResponse
    model.core.responses = [ModelResponse(stop_reason='length', text='截断回复')]
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'failed' and result['assistant_text'] == ''
    assert result['context_manifest']['sources'][0]['source_revision_id'] == revision.id


def test_unavailable_l1_storage_preserves_question_and_current_content(chat_api):
    """只有简介存储损坏时可降级，保存对话的外层事务仍能正常提交。"""
    client, db, model = chat_api
    db.get(Chapter, 1).chapter_number = 3; db.commit()
    db.execute(text('DROP TABLE chapter_digests')); db.commit()
    result = client.post('/api/writing-chat/1/turns', json=payload()).json()
    assert result['status'] == 'completed'
    assert result['context_manifest']['sources'] == []
    assert any('暂不可用' in warning for warning in result['context_manifest']['warnings'])
    assert '最新未保存原稿' in _first_content(model.core.calls[-1])
    assert db.query(WritingTurn).count() == 1


def test_old_turn_without_manifest_does_not_claim_a_reconstructed_source(chat_api):
    """旧对话缺来源时保留 null，不用当前简介回填伪造当时证据。"""
    client, db, _ = chat_api
    db.add(WritingTurn(novel_id=1, request_id=str(uuid4()), chapter_id=1, chapter_title='第一章',
        mode='discuss', user_text='旧问题', assistant_text='旧回答', status='completed', base_content_hash='0' * 64))
    db.commit()
    assert client.get('/api/writing-chat/1/turns').json()[0]['context_manifest'] is None
