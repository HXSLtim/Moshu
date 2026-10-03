"""Core Agent arguments 拼装层测试：稿件 content 明文增量提取。

旧链 runtime.py _ManuscriptArgsStreamer(:336-393)的替代：provider 事件已
结构化(toolcall_start/delta)，消解的是 JSON 前缀解码半边；本层保留的
半边=从 write_manuscript 的参数增量流里抽 content 明文，逐字推给作者。
语义=到达即推：每帧对已累积参数串做安全前缀解码，能解出多少明文就推
多少；尾部落在转义序列中间时回退到最近可解码边界。
"""
from app.services.conversation.core.assembly import ManuscriptStream


def _start(index=0, name='write_manuscript', tid='c1'):
    return {'type': 'toolcall_start', 'index': index, 'id': tid, 'name': name}


def _delta(args_delta, index=0):
    return {'type': 'toolcall_delta', 'index': index, 'args_delta': args_delta}


async def test_manuscript_content_streamed_across_frames():
    stream = ManuscriptStream()
    assert stream.feed(_start()) == ''
    assert stream.feed(_delta('{"operation": "append", "content": "第一')) == '第一'
    assert stream.feed(_delta('段')) == '段'
    assert stream.feed(_delta('正文')) == '正文'
    assert stream.feed(_delta('", "title": "t"}')) == ''


async def test_escape_boundary_held_back_until_safe():
    """delta 切在转义序列中间时，增量回退到最近可解码边界，不出坏字。"""
    stream = ManuscriptStream()
    stream.feed(_start())
    # 尾随单个反斜杠：转义序列未闭合，回退到不含它的前缀，"他说：" 即推。
    assert stream.feed(_delta('{"content": "他说：\\')) == '他说：'
    # 补齐 \" 后整帧可解码为 他说："继续，已推「他说：」，增量含解码后的引号。
    assert stream.feed(_delta('"继续')) == '"继续'
    assert stream.feed(_delta('续')) == '续'


async def test_unicode_escape_boundary():
    stream = ManuscriptStream()
    stream.feed(_start())
    assert stream.feed(_delta('{"content": "\\u4e')) == ''
    assert stream.feed(_delta('2d')) == '中'
    assert stream.feed(_delta('文')) == '文'


async def test_other_tools_produce_no_manuscript_delta():
    stream = ManuscriptStream()
    assert stream.feed(_start(name='read_chapter')) == ''
    assert stream.feed(_delta('{"chapter": 3}')) == ''


async def test_multiple_indices_tracked_independently():
    stream = ManuscriptStream()
    assert stream.feed(_start(index=0, name='read_chapter', tid='a')) == ''
    assert stream.feed(_start(index=1, name='write_manuscript', tid='b')) == ''
    assert stream.feed(_delta('{"content": "稿', index=1)) == '稿'
    assert stream.feed(_delta('件', index=1)) == '件'
    assert stream.feed(_delta('}', index=0)) == ''


async def test_partial_key_prefix_not_mistaken_as_content():
    """参数里其他键名(如 title)不能被误认成 content 起点。"""
    stream = ManuscriptStream()
    stream.feed(_start())
    assert stream.feed(_delta('{"title": "标题", "content": "正')) == '正'
    assert stream.feed(_delta('文')) == '文'
