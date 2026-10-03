"""Core Agent 提案工具面：规格与解析器。

与旧链 runtime.py 同源迁移(PROPOSE_TOOLS/_args/execute_agent_tool 逐行同款)，
双轨期两份并存、零改动旧链；P4 旧链下线时本文件成为唯一事实源。
提案工具只登记提案不写库，作者确认后才由命令接口落库——项目原则不变。
"""
from __future__ import annotations

import json

PROPOSE_TOOLS: list[dict] = [
    {
        'type': 'function',
        'function': {
            'name': 'propose_project_info',
            'description': '提议更新项目信息（类型、简介、世界观）。只在作者这次确实给出或修改了这些内容时调用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'genre': {'type': 'string', 'description': '小说类型，未涉及就不要传'},
                    'description': {'type': 'string', 'description': '小说简介，未涉及就不要传'},
                    'worldview': {'type': 'string', 'description': '完整世界观文本，未涉及就不要传'},
                },
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_entity',
            'description': '提议新增需要长期跟踪的人物、物品、地点或组织。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'entity_kind': {'type': 'string', 'enum': ['character', 'item', 'location', 'organization']},
                    'description': {'type': 'string', 'description': '一句话说明这个实体'},
                },
                'required': ['name', 'entity_kind', 'description'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_fact',
            'description': '提议记录一条可核对的设定事实，例如人物身份、位置、持有物、关系或世界规则。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'subject': {'type': 'string'},
                    'attribute': {'type': 'string'},
                    'value': {'type': 'string'},
                },
                'required': ['subject', 'attribute', 'value'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'propose_outline',
            'description': '提议补一条卷、阶段或章节的计划大纲。计划不代表已经发生。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'node_kind': {'type': 'string', 'enum': ['volume', 'chapter']},
                    'title': {'type': 'string'},
                    'chapter_number': {'type': 'integer', 'description': '章节号，写卷时不要传'},
                    'summary': {'type': 'string'},
                },
                'required': ['node_kind', 'title', 'summary'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'write_manuscript',
            'description': '作者让你接着写、改写本章或开新章时，提交完整正文稿件。不要用它回答普通问题。'
                           '正文的唯一交付通道：不要把草稿写进对话回复。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'operation': {'type': 'string', 'enum': ['append', 'rewrite', 'create']},
                    'content': {'type': 'string', 'description': '完整可用的正文，不要写占位或省略'},
                    'title': {'type': 'string', 'description': '仅开新章时给出章节标题'},
                    'uncertainties': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '本次创作中你不确定、替作者做过的假设，最多 12 条；没有就省略',
                    },
                },
                'required': ['operation', 'content'],
            },
        },
    },
]

SETTING_TOOLS = {'propose_project_info', 'propose_entity', 'propose_fact', 'propose_outline'}
OPERATION = {'append': 'append', 'rewrite': 'replace', 'create': 'create'}
MODE = {'append': 'continue', 'rewrite': 'rewrite', 'create': 'new_chapter'}

TOOLS_UNAVAILABLE_ACK = '本轮没有检索工具可用，请基于已有上下文回答，并说明该信息未能核实。'
DUPLICATE_CALL_ACK = '重复调用已忽略。'


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def execute_agent_tool(name: str, raw_args) -> tuple[dict | None, dict | None, str]:
    """执行一次提案/稿件工具调用。

    返回 ``(action, manuscript, ack)``；action 是待作者确认的设定提案，
    manuscript 是待确认的正文稿件。这里不接触数据库。
    """
    args = _args(raw_args)
    if name == 'propose_project_info':
        action = {'kind': 'project_info', 'genre': args.get('genre'), 'description': args.get('description'),
                  'worldview': args.get('worldview')}
        if not any(action[key] for key in ('genre', 'description', 'worldview')):
            return None, None, '没有可用字段，未登记提案。'
        return action, None, '已登记项目信息提案，等待作者确认。'
    if name == 'propose_entity':
        if not args.get('name') or args.get('entity_kind') not in {'character', 'item', 'location', 'organization'}:
            return None, None, '缺少名称或类型不合法，未登记提案。'
        return ({'kind': 'entity', 'name': str(args['name']), 'entity_kind': args['entity_kind'],
                 'description': str(args.get('description') or '')}, None, '已登记实体提案，等待作者确认。')
    if name == 'propose_fact':
        if not args.get('subject') or not args.get('attribute') or not args.get('value'):
            return None, None, '缺少主体、属性或值，未登记提案。'
        return ({'kind': 'fact', 'subject': str(args['subject']), 'attribute': str(args['attribute']),
                 'value': str(args['value'])}, None, '已登记设定事实提案，等待作者确认。')
    if name == 'propose_outline':
        if args.get('node_kind') not in {'volume', 'chapter'} or not args.get('title'):
            return None, None, '大纲类型或标题不合法，未登记提案。'
        number = args.get('chapter_number')
        if args['node_kind'] == 'chapter' and (not isinstance(number, int) or isinstance(number, bool) or number <= 0):
            return None, None, '章节大纲缺少合法章节号，未登记提案。'
        return ({'kind': 'outline', 'node_kind': args['node_kind'], 'title': str(args['title']),
                 'chapter_number': number if args['node_kind'] == 'chapter' else None,
                 'summary': str(args.get('summary') or '')}, None, '已登记大纲提案，等待作者确认。')
    if name == 'write_manuscript':
        if args.get('operation') not in OPERATION or not str(args.get('content') or '').strip():
            return None, None, '稿件不完整，未登记。'
        uncertainties = [str(item).strip()[:500] for item in (args.get('uncertainties') or [])
                         if isinstance(item, str) and item.strip()][:12]
        manuscript = {'operation': args['operation'], 'content': str(args['content']).strip(),
                      'title': str(args['title']).strip() if args.get('title') else None,
                      'uncertainties': uncertainties}
        return None, manuscript, '已收到正文稿件，等待作者采纳。'
    return None, None, f'未实现的工具：{name}'
