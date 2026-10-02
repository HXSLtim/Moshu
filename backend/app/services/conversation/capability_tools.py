"""Agent 的能力工具:编排、高级续写、选区改写、剧情走向与资料检索。

这些工具由对话 Agent 按作者意图自主调用(而非作者手动选面板)。稿件类
工具在工具内部生成候选提案并挂当前任务,由任务完成后的审核模式钩子统一
决定是否自动采纳;回传给模型的只有摘要,不回传全文,模型不转抄正文。

所有工具整体包错:失败返回可读的中文摘要,让模型改用自然语言向作者说明,
不影响本轮对话的终态守卫。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from loguru import logger

from app.services.context.budget import (
    MAX_CHAT_OUTPUT_CHARS,
    MAX_STORY_CONTEXT_CHARS,
    compact_text,
)

CAPABILITY_TOOL_NAMES = {'workflow_continue', 'orchestrate', 'rewrite_selection', 'plot_options', 'research_web'}

CAPABILITY_TOOL_SPECS: list[dict] = [
    {
        'type': 'function',
        'function': {
            'name': 'workflow_continue',
            'description': '三角色高级续写工作流(检索→世界观→角色→剧情→一致性→重试)。作者要写重头戏、长段落或高质量打磨时用它,普通续写不要用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'instruction': {'type': 'string', 'description': '创作要求,如场景、冲突、氛围'},
                    'target_length': {'type': 'integer', 'description': '目标字数,默认约 800'},
                },
                'required': ['instruction'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'orchestrate',
            'description': '复合任务编排:把「先查X、再写Y、最后检查Z」这类多步指令分解为计划并执行。作者一句话里含两个以上先后步骤时用它。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'instruction': {'type': 'string', 'description': '完整的复合任务描述'},
                },
                'required': ['instruction'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'rewrite_selection',
            'description': '改写作者当前在编辑器中选中的一段文字。作者说"把这段改得…"时用它;没有选区时调用会得到提示。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'instruction': {'type': 'string', 'description': '改写要求,如更有火药味、更简洁'},
                },
                'required': ['instruction'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'plot_options',
            'description': '基于当前设定与正文,生成多个可选的剧情走向供作者挑选。作者问"接下来可以怎么写"时用它。',
            'parameters': {'type': 'object', 'properties': {}},
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'research_web',
            'description': '检索公共资料(中文维基百科):历史、制度、地理、专业常识等书外知识。写进正文前需要核实的背景知识用它,书内设定用检索账本工具。',
            'parameters': {
                'type': 'object',
                'properties': {'query': {'type': 'string', 'description': '检索词或问题'}},
                'required': ['query'],
            },
        },
    },
]


@dataclass(frozen=True)
class CapabilityContext:
    """一轮对话内冻结的能力执行上下文;选区缺失时 selection_* 为空。"""

    novel_id: int
    actor_id: int
    novel_lifecycle_id: str
    chapter_id: int
    chapter_number: int
    chapter_version: int
    chapter_lifecycle_id: str
    current_content: str
    current_day: int | None
    selection_text: str | None = None
    selection_start: int | None = None
    selection_end: int | None = None
    context_pack: Any = None  # ContextPack,编排工具复用
    llm: Any = None  # 编排规划用模型


def _proposal_summary(proposal, extra: str = '') -> str:
    text = f'候选提案已生成(编号 {str(proposal.id)[:8]}),按本书审核模式处理,等待采纳或已自动采纳。{extra}'
    return compact_text(text, 600, keep='both')


def _create_manuscript_proposal(context: CapabilityContext, content: str, operation: str,
                                title: str | None = None, *, selection: bool = False) -> str:
    """在独立会话中落候选提案,挂当前任务供审核模式钩子处理。"""
    from app.db.base import SessionLocal
    from app.services.conversation.proposals import create_proposal
    with SessionLocal() as db:
        proposal = create_proposal(
            db,
            novel=SimpleNamespace(id=context.novel_id, rag_lifecycle_id=context.novel_lifecycle_id),
            actor_id=context.actor_id,
            chapter=SimpleNamespace(id=context.chapter_id, version=context.chapter_version,
                                    rag_lifecycle_id=context.chapter_lifecycle_id),
            base_content=context.current_content, operation=operation, content=content, title=title,
            **({'selection_start': context.selection_start, 'selection_end': context.selection_end} if selection else {}),
        )
        db.commit()
        return _proposal_summary(proposal)


async def execute_capability_tool(context: CapabilityContext, name: str, args: dict) -> str:
    """执行一次能力工具,返回给模型的中文摘要;失败返回可读原因。"""
    try:
        if name == 'workflow_continue':
            return await _workflow_continue(context, args)
        if name == 'orchestrate':
            return await _orchestrate(context, args)
        if name == 'rewrite_selection':
            return await _rewrite_selection(context, args)
        if name == 'plot_options':
            return await _plot_options(context)
        if name == 'research_web':
            return await _research_web(str(args.get('query') or ''))
        return f'未实现的能力工具:{name}'
    except Exception as exc:  # noqa: BLE001
        logger.warning('能力工具 {} 执行失败: {}', name, exc)
        return f'工具 {name} 执行失败({type(exc).__name__}),请向作者说明并用自然语言继续。'


async def _workflow_continue(context: CapabilityContext, args: dict) -> str:
    from app.models.schemas import GenerationRequest
    from app.services.generation.workflow import generation_workflow
    instruction = compact_text(str(args.get('instruction') or ''), 2000, keep='both')
    if not instruction.strip():
        return '续写要求为空,请先向作者确认要写什么。'
    target = args.get('target_length')
    response = await generation_workflow.generate_content(
        GenerationRequest(novel_id=context.novel_id, chapter=context.chapter_number,
                          prompt=instruction, current_day=context.current_day,
                          target_length=int(target) if isinstance(target, int) and target >= 100 else 800),
        actor_id=context.actor_id, novel_lifecycle_id=context.novel_lifecycle_id)
    consistency = response.final_consistency.status if response.final_consistency else '未知'
    return _create_manuscript_proposal(
        context, response.final_content, 'append',
        extra=f'高级续写 {len(response.final_content)} 字,一致性:{consistency}(重试 {response.retry_count} 次)。')


async def _orchestrate(context: CapabilityContext, args: dict) -> str:
    from app.services.generation.orchestrator import run_orchestration
    instruction = compact_text(str(args.get('instruction') or ''), 2000, keep='both')
    if not instruction.strip():
        return '编排指令为空,请先向作者确认任务内容。'
    result = await run_orchestration(
        llm=context.llm, instruction=instruction, context_pack=context.context_pack,
        current_content=context.current_content,
        scope=SimpleNamespace(novel_id=context.novel_id, actor_id=context.actor_id,
                              novel_lifecycle_id=context.novel_lifecycle_id,
                              target_chapter=context.chapter_number, current_day=context.current_day),
        novel_id=context.novel_id, target_chapter=context.chapter_number, current_day=context.current_day)
    plan_kinds = [step.get('kind') for step in result.plan.get('steps', [])]
    consistency = (result.consistency or {}).get('has_conflict')
    return _create_manuscript_proposal(
        context, result.text, 'append',
        extra=f'编排 {len(plan_kinds)} 步({"→".join(plan_kinds)}),产出 {len(result.text)} 字;'
              f'一致性:{"有冲突,采纳前请核对" if consistency else "未发现冲突"};'
              f'不确定点 {len(result.uncertainties)} 条,细节见任务记录。')


async def _rewrite_selection(context: CapabilityContext, args: dict) -> str:
    if not (context.selection_text or '').strip() or type(context.selection_start) is not int:
        return '作者当前没有选中文字。请提醒作者先在编辑器中选中要改写的段落,再发出改写要求。'
    instruction = compact_text(str(args.get('instruction') or ''), 1000, keep='both')
    from app.services.context.budget import ensure_generation_prompt_budget
    from app.services.model.execution import invoke_model
    from app.services.model.result import parse_model_result
    prompt = f'改写以下中文小说片段。要求:{instruction or "保持原意,提升表现力"}。\n只输出改写后的文本本身。\n【原文】\n{context.selection_text}'
    messages = [('system', '你是中文小说改写助手,只输出改写后的正文本身,不解释。'),
                ('human', ensure_generation_prompt_budget(prompt))]
    output = parse_model_result(await invoke_model(context.llm, messages), max_output_chars=MAX_CHAT_OUTPUT_CHARS)
    return _create_manuscript_proposal(
        context, output.text, 'replace_selection', selection=True,
        extra=f'选区改写完成,原文 {len(context.selection_text)} 字 → 候选 {len(output.text)} 字。')


async def _plot_options(context: CapabilityContext) -> str:
    from app.services.context.budget import ensure_generation_prompt_budget
    from app.services.model.execution import invoke_model
    from app.services.model.result import parse_model_result
    tail = compact_text(context.current_content, MAX_STORY_CONTEXT_CHARS, keep='tail') or '(正文为空)'
    prompt = ('基于以下小说当前正文结尾,设计 3 个差异明显的下一步剧情走向。'
              '每个走向用两三句话说明:核心事件、对主角的影响、与现有伏笔的呼应。只输出选项本身。\n【正文结尾】\n' + tail)
    messages = [('system', '你是小说剧情策划,输出 3 个编号选项,不输出解释性开场白。'),
                ('human', ensure_generation_prompt_budget(prompt))]
    output = parse_model_result(await invoke_model(context.llm, messages), max_output_chars=6000)
    return compact_text('剧情走向选项已生成,请原样转述给作者让其挑选:\n' + output.text, 3000, keep='both')


async def _research_web(query: str) -> str:
    query = compact_text(query, 200, keep='head').strip()
    if not query:
        return '检索词为空,未执行查询。'

    def _fetch() -> str:
        import json as _json
        from httpx import AsyncClient
        import asyncio as _asyncio

        async def _run():
            async with AsyncClient(timeout=10.0) as client:
                resp = await client.get('https://zh.wikipedia.org/w/api.php', params={
                    'action': 'query', 'list': 'search', 'format': 'json',
                    'srsearch': query, 'srlimit': 4})
                if resp.status_code != 200:
                    return ''
                items = resp.json().get('query', {}).get('search', [])
                lines = [f"- {item.get('title')}:"
                         f"{compact_text(str(item.get('snippet') or ''), 300, keep='head')}"
                         for item in items]
                return '\n'.join(lines)
        return _asyncio.run(_run())

    result = await asyncio.to_thread(_fetch)
    if not result:
        return '公共资料检索暂不可用,请向作者说明该信息未能核实。'
    return compact_text('【公共资料检索结果(维基百科,仅供参考,写作时按需核实)】\n' + result,
                        3000, keep='both')
