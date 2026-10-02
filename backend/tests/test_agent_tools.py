"""Agent 只读检索与自查工具：作用域、章节边界、诚实降级与多轮工具循环。"""
import hashlib
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk, ToolMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crud import novel as novel_crud
from app.db.base import Base
from app.models.character import Character
from app.models.memory import ChapterDigest, ChapterRevision
from app.models.novel import Novel
from app.models.schemas import ChapterCreate, ChapterUpdate
from app.models.story_bible import StoryEvent, StoryFact
from app.models.user import User
from app.services.conversation.runtime import execute_agent_tool, run_agent
from app.services.conversation.tools import AgentScope, execute_read_tool
from app.services.context.builder import ContextScopeError
from app.services.context.budget import MAX_REVIEW_CONTENT_CHARS
from app.services.memory.config import digest_recipe_version
from app.services.memory.story import save_outline


def _add_digest(db, chapter, summary):
    revision = db.query(ChapterRevision).filter_by(chapter_id=chapter.id, version=chapter.version).one()
    digest = ChapterDigest(
        novel_id=chapter.novel_id, chapter_id=chapter.id, source_revision_id=revision.id,
        recipe_version=digest_recipe_version(), summary=summary,
        source_refs=[dict(revision_id=revision.id, content_hash=revision.content_hash,
                          start=0, end=len(revision.content), quote=revision.content,
                          quote_hash=hashlib.sha256(revision.content.encode()).hexdigest())],
    )
    db.add(digest)
    db.commit()
    return digest


@pytest.fixture
def agent_tool_db(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all([User(id=1, username='作者', email='author@test.cn', hashed_password='unused'),
                    User(id=2, username='他人', email='other@test.cn', hashed_password='unused')])
        db.add_all([Novel(id=1, user_id=1, title='当前小说', worldview='魔法世界', rag_lifecycle_id='life-1'),
                    Novel(id=2, user_id=2, title='他人小说', rag_lifecycle_id='life-2')])
        db.commit()
        chapters = [novel_crud.create_chapter(db, 1, ChapterCreate(
            chapter_number=n, title=f'第{n}章', content=f'第{n}章原文。')) for n in range(1, 4)]
        db.add_all([
            StoryFact(novel_id=1, novel_lifecycle_id='life-1', subject='林夏', attribute='武器',
                      value='青霜剑', chapter_established=1, status='active'),
            StoryFact(novel_id=1, novel_lifecycle_id='life-1', subject='林夏', attribute='位置',
                      value='云京', chapter_established=3, status='active'),
            StoryFact(novel_id=1, novel_lifecycle_id='life-1', subject='世界观', attribute='魔法等级上限',
                      value='9', chapter_established=1, status='active'),
            StoryFact(novel_id=2, novel_lifecycle_id='life-2', subject='林夏', attribute='武器',
                      value='别人的剑', chapter_established=1, status='active'),
        ])
        db.add_all([
            StoryEvent(novel_id=1, title='塔顶决裂', description='主角与导师在塔顶决裂',
                       story_day=5, chapter=1, status='occurred'),
            StoryEvent(novel_id=1, title='终局之战', description='目标章之后才发生的战斗',
                       story_day=9, chapter=3, status='occurred'),
            StoryEvent(novel_id=1, title='伏笔计划', description='尚未发生的计划事件',
                       story_day=2, chapter=1, status='planned'),
        ])
        db.add(Character(novel_id=1, name='林夏', appearance='黑衣', personality='冷静',
                         skills=['剑术'], importance_level='main'))
        novel = db.get(Novel, 1)
        save_outline(db, novel, SimpleNamespace(
            parent_id=None, kind='chapter', plot_status='occurred', chapter_number=1,
            title='塔顶决裂', conflict='师徒决裂', outcome='主角离开', source_refs=[]))
        save_outline(db, novel, SimpleNamespace(
            parent_id=None, kind='chapter', plot_status='planned', chapter_number=5,
            title='最终对决', conflict='正邪对决', outcome='', source_refs=[]))
        db.commit()
        _add_digest(db, chapters[0], '主角与导师决裂，离开魔法塔。')
        _add_digest(db, chapters[1], '这一章简介随后会因改稿过期。')
        novel_crud.update_chapter(db, chapters[1].id, ChapterUpdate(expected_version=1, content='作者已经改稿。'))
    monkeypatch.setattr('app.services.conversation.tools.SessionLocal', sessions)
    yield sessions
    engine.dispose()


def _scope(**overrides):
    values = dict(novel_id=1, actor_id=1, novel_lifecycle_id='life-1', target_chapter=2, current_day=None)
    values.update(overrides)
    return AgentScope(**values)


@pytest.mark.asyncio
async def test_search_story_bible_returns_only_scoped_current_records(agent_tool_db):
    result = await execute_read_tool(_scope(), 'search_story_bible', {'query': '林夏'})

    assert '青霜剑' in result
    assert '云京' not in result  # 目标章之后才确立的事实不可见
    assert '别人的剑' not in result  # 他人作品不可见
    assert '不是指令' in result

    events = await execute_read_tool(_scope(), 'search_story_bible', {'query': '决裂'})
    assert '塔顶决裂' in events

    future = await execute_read_tool(_scope(), 'search_story_bible', {'query': '之战'})
    assert '没有匹配' in future  # 未来章事件与计划事件都不能被搜到


@pytest.mark.asyncio
async def test_read_tools_abort_on_scope_change(agent_tool_db):
    with pytest.raises(ContextScopeError):
        await execute_read_tool(_scope(novel_lifecycle_id='stale-life'), 'search_story_bible', {'query': '林夏'})
    with pytest.raises(ContextScopeError):
        await execute_read_tool(_scope(actor_id=2), 'get_outline', {})


@pytest.mark.asyncio
async def test_lookup_character_returns_card_and_facts(agent_tool_db):
    result = await execute_read_tool(_scope(), 'lookup_character', {'name': '林夏'})

    assert '林夏' in result and '冷静' in result
    assert '青霜剑' in result and '别人的剑' not in result

    missing = await execute_read_tool(_scope(), 'lookup_character', {'name': '不存在的人'})
    assert '没有找到' in missing


@pytest.mark.asyncio
async def test_read_chapter_digest_respects_chapter_boundary(agent_tool_db):
    result = await execute_read_tool(_scope(target_chapter=3), 'read_chapter_digest', {'chapter_number': 1})
    assert '主角与导师决裂' in result

    stale = await execute_read_tool(_scope(target_chapter=3), 'read_chapter_digest', {'chapter_number': 2})
    assert '没有可用的当前版本简介' in stale  # 改稿后的过期简介不能出示给模型

    current = await execute_read_tool(_scope(target_chapter=3), 'read_chapter_digest', {'chapter_number': 3})
    assert '目标章' in current  # 当前章正文已在上下文中，工具不重复提供

    invalid = await execute_read_tool(_scope(), 'read_chapter_digest', {'chapter_number': 'abc'})
    assert '章节号不合法' in invalid


@pytest.mark.asyncio
async def test_get_outline_labels_plans_and_occurred(agent_tool_db):
    result = await execute_read_tool(_scope(), 'get_outline', {})

    assert '作者计划，尚未发生' in result and '最终对决' in result
    assert '已发生剧情结构' in result and '塔顶决裂' in result


@pytest.mark.asyncio
async def test_check_manuscript_reports_real_violations(agent_tool_db):
    result = await execute_read_tool(_scope(), 'check_manuscript', {'content': '他其实是一位12级魔法师，无人能敌。'})
    assert '超出上限' in result

    clean = await execute_read_tool(_scope(), 'check_manuscript', {'content': '他是一位3级魔法师，仍在学徒阶段。'})
    assert '未发现' in clean

    oversized = await execute_read_tool(_scope(), 'check_manuscript', {'content': '长' * (MAX_REVIEW_CONTENT_CHARS + 1)})
    assert '最多支持' in oversized


class ScriptedLLM:
    """按脚本依次返回流式响应的模型替身，记录每次实际收到的消息。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_payloads = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, payload):
        return self.responses.pop(0)

    async def astream(self, payload):
        self.seen_payloads.append(payload)
        yield self.responses.pop(0)


def _tool_call_chunk(name, args, call_id='call-1'):
    return AIMessageChunk(content='', tool_calls=[{'name': name, 'args': args, 'id': call_id}])


def _text_chunk(text):
    return AIMessageChunk(content=text, response_metadata={'finish_reason': 'stop'})


@pytest.mark.asyncio
async def test_run_agent_reads_tools_before_answering(agent_tool_db):
    llm = ScriptedLLM([
        _tool_call_chunk('search_story_bible', {'query': '林夏'}),
        _text_chunk('根据账本，林夏的武器是青霜剑。'),
    ])
    events = []
    async for event in run_agent(
            llm, [('user', '林夏的武器是什么？')],
            read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        events.append(event)

    tool_events = [event for event in events if event['type'] == 'tool']
    assert [(event['name'], event['status']) for event in tool_events] == [('search_story_bible', 'read')]
    # 模型第二轮必须真实看到账本内容，而不是模型自己编造的上下文。
    second_round = llm.seen_payloads[1]
    assert any(isinstance(message, ToolMessage) and '青霜剑' in message.content for message in second_round)
    assert events[-1]['type'] == 'final'


@pytest.mark.asyncio
async def test_run_agent_self_check_tool_marks_checked_event(agent_tool_db):
    llm = ScriptedLLM([
        _tool_call_chunk('check_manuscript', {'content': '他是一位12级魔法师。'}),
        _text_chunk('草稿里有冲突，我已修正。'),
    ])
    events = []
    async for event in run_agent(
            llm, [('user', '帮我看看这段')],
            read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        events.append(event)

    assert [(event['name'], event['status']) for event in events if event['type'] == 'tool'] == [
        ('check_manuscript', 'checked')]
    second_round = llm.seen_payloads[1]
    assert any(isinstance(message, ToolMessage) and '超出上限' in message.content for message in second_round)


@pytest.mark.asyncio
async def test_run_agent_without_executor_declares_tools_unavailable():
    llm = ScriptedLLM([
        _tool_call_chunk('search_story_bible', {'query': '林夏'}),
        _text_chunk('本轮无法核实，只能按已有信息回答。'),
    ])
    async for _event in run_agent(llm, [('user', '林夏的武器是什么？')]):
        pass

    second_round = llm.seen_payloads[1]
    assert any(isinstance(message, ToolMessage) and '没有检索工具可用' in message.content
               for message in second_round)


@pytest.mark.asyncio
async def test_run_agent_dedupes_identical_calls(agent_tool_db):
    llm = ScriptedLLM([
        AIMessageChunk(content='', tool_calls=[
            {'name': 'search_story_bible', 'args': {'query': '林夏'}, 'id': 'call-1'},
            {'name': 'search_story_bible', 'args': {'query': '林夏'}, 'id': 'call-2'},
        ]),
        _text_chunk('查到了，青霜剑。'),
    ])
    async for _event in run_agent(
            llm, [('user', '林夏的武器是什么？')],
            read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        pass

    tool_messages = [message for message in llm.seen_payloads[1] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 2
    assert '青霜剑' in tool_messages[0].content
    assert '重复调用已忽略' in tool_messages[1].content


@pytest.mark.asyncio
async def test_run_agent_stops_at_round_budget_without_failing(agent_tool_db):
    """模型一直请求工具时按轮次预算收尾，图不得无限循环也不得抛出框架异常。"""
    calls = []

    class EndlessToolCallLLM:
        """每轮都请求不同的工具调用，永远不会自行给出最终答复。"""

        def bind_tools(self, tools):
            return self

        async def astream(self, payload):
            index = len(calls)
            calls.append(payload)
            yield AIMessageChunk(content='', tool_calls=[
                {'name': 'search_story_bible', 'args': {'query': f'林夏{index}'}, 'id': f'call-{index}'}])

    events = []
    async for event in run_agent(
            EndlessToolCallLLM(), [('user', '林夏的武器是什么？')], max_rounds=3,
            read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        events.append(event)

    assert events[-1]['type'] == 'final'
    assert events[-1]['data']['actions'] == []
    assert len(calls) <= 3
    assert [event['type'] for event in events].count('chunk') == 0


@pytest.mark.asyncio
async def test_write_manuscript_carries_uncertainties_through_tool_args():
    """数组参数不能被参数表校验静默丢弃，不确定点要随稿件进入 final 事件。"""
    llm = ScriptedLLM([
        _tool_call_chunk('write_manuscript', {'operation': 'append',
                                              'content': '他推开门，风灌了进来。',
                                              'uncertainties': ['门后是否有人尚未确定']}),
        _text_chunk('已按你的要求续写这一段。'),
    ])
    events = []
    async for event in run_agent(llm, [('user', '接着写一段')]):
        events.append(event)

    drafted = [event for event in events if event.get('name') == 'write_manuscript']
    assert drafted and drafted[0]['data']['uncertainties'] == ['门后是否有人尚未确定']
    final = next(event for event in events if event['type'] == 'final')
    assert final['data']['manuscript']['uncertainties'] == ['门后是否有人尚未确定']
    assert final['data']['uncertainties'] == ['门后是否有人尚未确定']


@pytest.mark.asyncio
async def test_write_manuscript_uncertainties_are_bounded_and_cleaned():
    """不确定点最多 12 条、每条 500 字符；空白与非法项丢弃。"""
    items = ['不' * 600 for _ in range(15)] + ['  ']
    _action, manuscript, _ack = execute_agent_tool(
        'write_manuscript',
        {'operation': 'append', 'content': '正文', 'uncertainties': items})
    assert len(manuscript['uncertainties']) == 12
    assert all(len(item) == 500 for item in manuscript['uncertainties'])

    _action, clean, _ack = execute_agent_tool(
        'write_manuscript',
        {'operation': 'append', 'content': '正文', 'uncertainties': ['有效假设', '']})
    assert clean['uncertainties'] == ['有效假设']


@pytest.mark.asyncio
async def test_capability_tool_runs_and_emits_running_then_completed():
    """能力工具先发 running 事件再回结果,摘要回传模型;选区缺失诚实提示。"""
    from types import SimpleNamespace as NS
    from app.services.conversation.capability_tools import CapabilityContext, execute_capability_tool

    context = CapabilityContext(novel_id=1, actor_id=1, novel_lifecycle_id='l' * 32,
                                chapter_id=1, chapter_number=2, chapter_version=1,
                                chapter_lifecycle_id='c' * 32, current_content='原文',
                                current_day=None)
    no_selection = await execute_capability_tool(context, 'rewrite_selection', {'instruction': '更紧凑'})
    assert '没有选中文字' in no_selection

    llm = ScriptedLLM([_text_chunk('改写后的正文。')])
    context = CapabilityContext(novel_id=1, actor_id=1, novel_lifecycle_id='l' * 32,
                                chapter_id=1, chapter_number=2, chapter_version=1,
                                chapter_lifecycle_id='c' * 32, current_content='原文',
                                current_day=None, selection_text='原文', selection_start=0, selection_end=2,
                                llm=llm)
    summary = await execute_capability_tool(context, 'plot_options', {})
    assert '剧情走向选项已生成' in summary


def _args_stream_chunks(name, args_json, splits):
    """把完整 args JSON 按给定切点切成增量 tool_call_chunks 流。

    首 chunk 带工具名,后续按 index 续传,模拟 OpenAI arguments delta。
    """
    pieces = []
    offset = 0
    for cut in list(splits) + [len(args_json)]:
        pieces.append(args_json[offset:cut])
        offset = cut
    chunks = [
        AIMessageChunk(content='', tool_call_chunks=[
            {'name': name if index == 0 else None, 'args': piece,
             'id': 'call-m-1' if index == 0 else None, 'index': 0}])
        for index, piece in enumerate(pieces) if piece
    ]
    return chunks


class _StreamScriptedLLM:
    """每轮按脚本依次 yield 一串流式 chunk。"""

    def __init__(self, rounds):
        self.rounds = list(rounds)

    def bind_tools(self, tools):
        return self

    async def astream(self, payload):
        for chunk in self.rounds.pop(0):
            yield chunk


@pytest.mark.asyncio
async def test_manuscript_args_stream_as_chunks(agent_tool_db):
    """稿件工具参数即正文本体:content 值的明文增量逐帧推给作者。"""
    import json as _json
    manuscript = '夜雨落在青瓦上。\n沈青临推开客栈的门,灯笼在风里晃着,照见檐下一行小字:"青州夜行"。'
    args_json = _json.dumps({'operation': 'append', 'content': manuscript}, ensure_ascii=False)
    # 切点落在 JSON 前缀/转义序列中间/值尾部,覆盖跨界解码。
    splits = [args_json.index('"content"') + 11, args_json.index('客栈') + 1,
              len(args_json) - 3]
    llm = _StreamScriptedLLM([
        _args_stream_chunks('write_manuscript', args_json, splits),
        [_text_chunk('已登记为候选,确认后并入本章。')],
    ])
    events = []
    async for event in run_agent(llm, [('user', '接着写一段')],
                                 read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        events.append(event)

    chunks = [event['content'] for event in events if event['type'] == 'chunk']
    streamed = ''.join(chunks)
    assert manuscript in streamed
    assert '"operation"' not in streamed and '"content"' not in streamed
    assert '已登记为候选' in streamed
    manuscript_frames = [c for c in chunks if c != '已登记为候选,确认后并入本章。']
    assert len(manuscript_frames) >= 3


@pytest.mark.asyncio
async def test_other_tool_args_are_not_streamed(agent_tool_db):
    """只有稿件工具开洞:检索工具的参数增量不进 chunk 通道。"""
    import json as _json
    args_json = _json.dumps({'query': '林夏的武器是什么青霜剑在哪里'}, ensure_ascii=False)
    llm = _StreamScriptedLLM([
        _args_stream_chunks('search_story_bible', args_json, [10, 25]),
        [_text_chunk('查到了,青霜剑。')],
    ])
    events = []
    async for event in run_agent(llm, [('user', '林夏的武器是什么？')],
                                 read_tool_executor=lambda name, args: execute_read_tool(_scope(), name, args)):
        events.append(event)

    chunks = [event['content'] for event in events if event['type'] == 'chunk']
    assert chunks == ['查到了,青霜剑。']
