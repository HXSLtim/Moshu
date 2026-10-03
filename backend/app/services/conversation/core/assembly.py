"""Core Agent arguments 拼装层：稿件 content 明文增量提取。

provider 事件已结构化(toolcall_start/delta)，JSON 前缀解码的纯函数与旧链
runtime.py(:333-393)同款——core 与 LangChain 解耦故原文移植，双轨结束后
随旧链一并退役。每帧对已累积的参数串做安全前缀解码，尾部落在转义序列
中间时回退到最近可解码边界，与已推前缀的差值即本次明文增量。
"""
from __future__ import annotations

import json
import re

_MANUSCRIPT_TOOL_NAME = 'write_manuscript'
_CONTENT_KEY_RE = re.compile(r'"content"\s*:\s*"')


class ManuscriptStream:
    """从 write_manuscript 的参数增量流里逐字提取 content 明文。"""

    def __init__(self) -> None:
        self._names: dict[int, str] = {}
        self._args: dict[int, str] = {}
        self._content_at: dict[int, int] = {}
        self._pushed: dict[int, int] = {}

    def feed(self, event: dict) -> str:
        """吃一个 provider 工具调用事件，返回本次可安全推送的明文增量。"""
        index = event.get('index', 0)
        if event['type'] == 'toolcall_start':
            self._names[index] = event.get('name') or ''
            return ''
        if event['type'] != 'toolcall_delta':
            return ''
        if self._names.get(index) != _MANUSCRIPT_TOOL_NAME:
            return ''
        self._args[index] = self._args.get(index, '') + (event.get('args_delta') or '')
        return self._drain(index)

    def _drain(self, index: int) -> str:
        raw = self._args[index]
        start = self._content_at.get(index)
        if start is None:
            match = _CONTENT_KEY_RE.search(raw)
            if match is None:
                return ''
            start = self._content_at[index] = match.end()
        decoded = _decode_json_string_prefix(raw[start:])
        if not decoded:
            return ''
        piece = decoded[self._pushed.get(index, 0):]
        self._pushed[index] = len(decoded)
        return piece


def _decode_json_string_prefix(value: str):
    """解码 JSON 字符串值的安全前缀；尾部落在转义序列中间时回退。"""
    for cut in range(len(value), -1, -1):
        candidate = value[:cut]
        if candidate.endswith('\\'):
            continue
        try:
            return json.loads('"' + candidate + '"')
        except ValueError:
            continue
    return None
