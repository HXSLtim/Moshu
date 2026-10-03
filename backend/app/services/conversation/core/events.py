"""Core Agent 事件序适配层：Nai 前端事件形状的守护与锁定。

「前端零改动」验收线(设计稿 §3.6)的承载件：loop 出口即旧链 Nai 形状
(tool/chunk/final)，本模块把形状契约显式化为可编程校验——双轨切换与
P4 灰度期间，任何事件形状漂移在测试期即暴露，而非到前端才炸。
形状基准=旧链 runtime.py 的 publish 面 + writing_chat.py:175-198 消费逻辑。
"""
from __future__ import annotations

TOOL_STATUSES = {'read', 'checked', 'running', 'completed', 'proposed', 'drafted'}
FINAL_OPERATIONS = {None, 'append', 'replace', 'create'}


def validate_nai_event(event: dict) -> list[str]:
    """校验一个事件是否符合 Nai 前端契约，返回违规项列表(空=合规)。"""
    violations: list[str] = []
    kind = event.get('type')
    if kind == 'chunk':
        if not isinstance(event.get('content'), str):
            violations.append('chunk.content 必须是字符串')
        return violations
    if kind == 'tool':
        if not isinstance(event.get('name'), str) or not event.get('name'):
            violations.append('tool.name 必须是非空字符串')
        if event.get('status') not in TOOL_STATUSES:
            violations.append(f'tool.status 必须是 {sorted(TOOL_STATUSES)} 之一')
        if not isinstance(event.get('data'), dict):
            violations.append('tool.data 必须是对象')
        return violations
    if kind == 'final':
        data = event.get('data')
        if not isinstance(data, dict):
            violations.append('final.data 必须是对象')
            return violations
        for key in ('actions', 'uncertainties', 'decided_mode', 'stop_reason'):
            if key not in data:
                violations.append(f'final.data.{key} 缺失')
        if data.get('decided_mode') not in {'discuss', 'continue', 'rewrite', 'new_chapter'}:
            violations.append('final.data.decided_mode 取值非法')
        if event.get('operation') not in FINAL_OPERATIONS:
            violations.append('final.operation 取值非法')
        if event.get('text') is not None and not isinstance(event.get('text'), str):
            violations.append('final.text 必须是字符串或 null(仅稿件轮有值)')
        return violations
    violations.append(f'未知事件类型：{kind!r}')
    return violations


def assert_nai_event(event: dict) -> dict:
    """校验并原样返回；违规即抛断言错误——切换点诊断用。"""
    violations = validate_nai_event(event)
    if violations:
        raise AssertionError(f'事件形状漂移：{event.get("type")} -> {"; ".join(violations)}')
    return event
