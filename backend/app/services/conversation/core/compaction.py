"""Core Agent 压缩链：混合计量、切点纪律、六节摘要与失败纪律(设计稿 §3.2)。

参考 pi compaction.ts 移植、按 Nai 域收敛：估算系数 chars/3(中文起步，选型
会⑤——不引真 tokenizer，主力口径=provider 实报)；切点绝不落在 tool 结果
与其调用之间；切开轮次单独生成 turn-prefix 摘要；摘要函数注入——生产端
负责失败纪律(stopReason error/length 抛错，残缺文本不得成为会话检查点)，
本层透传摘要器异常即「拒落盘」。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

# 中文估算系数：1 汉字约 0.6-0.7 token，chars/3 保守起步；主力是 provider 实报。
_CHARS_PER_TOKEN = 3


@dataclass
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 32000  # Nai 域初值：保整章+近三轮(设计稿 §3.2)


def estimate_message_tokens(message: dict) -> int:
    """单条消息 chars/3 估算；含工具调用的 assistant 连参数一起计。"""
    content = message.get('content') or ''
    chars = len(content) if isinstance(content, str) else len(str(content))
    for call in message.get('tool_calls') or []:
        function = call.get('function') or {}
        chars += len(function.get('name') or '') + len(function.get('arguments') or '')
    return math.ceil(chars / _CHARS_PER_TOKEN)


def _valid_usage(message: dict) -> dict | None:
    """最后有效 usage：aborted/error/全零不采信(null 不伪造纪律)。"""
    usage = message.get('usage')
    if message.get('role') != 'assistant' or not isinstance(usage, dict):
        return None
    if (usage.get('total') or 0) <= 0:
        return None
    return usage


def estimate_context_tokens(messages: list[dict]) -> dict:
    """混合计量：最后一次有效 assistant usage(实报) + 其后消息估算补尾。"""
    last_usage_index = -1
    usage_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        usage = _valid_usage(messages[index])
        if usage is not None:
            last_usage_index = index
            usage_tokens = int(usage.get('total') or 0)
            break
    if last_usage_index < 0:
        estimated = sum(estimate_message_tokens(m) for m in messages)
        return {'tokens': estimated, 'usage_tokens': 0, 'trailing_tokens': estimated}
    trailing = sum(estimate_message_tokens(m) for m in messages[last_usage_index + 1:])
    return {'tokens': usage_tokens + trailing, 'usage_tokens': usage_tokens,
            'trailing_tokens': trailing}


def should_compact(context_tokens: int, context_window: int, settings: CompactionSettings) -> bool:
    if not settings.enabled:
        return False
    return context_tokens > context_window - settings.reserve_tokens


def _is_valid_cut(message: dict) -> bool:
    """合法切点=user/assistant；绝不切在 tool 结果上(必须跟着其调用)。"""
    return message.get('role') in ('user', 'assistant')


def _is_turn_start(message: dict) -> bool:
    return message.get('role') == 'user'


def find_cut_point(messages: list[dict], keep_recent_tokens: int) -> dict:
    """从最新往回累积到 keep_recent 处切；返回切点与轮切开信息。

    切在带 tool_calls 的 assistant 上时，其 tool 结果自然跟入保留区
    (保留区是从切点起的连续后缀)。
    """
    valid = [i for i, m in enumerate(messages) if _is_valid_cut(m)]
    if not valid:
        return {'first_kept_index': 0, 'turn_start_index': -1, 'is_split_turn': False}
    accumulated = 0
    cut = valid[0]
    for i in range(len(messages) - 1, -1, -1):
        tokens = estimate_message_tokens(messages[i])
        if tokens == 0:
            continue
        accumulated += tokens
        if accumulated >= keep_recent_tokens:
            # 越线处吸附到其后最近合法切点；越线本身落在 tool 区时不切 tool。
            candidates = [c for c in valid if c >= i]
            cut = candidates[0] if candidates else valid[-1]
            break
    boundary = messages[cut]
    if _is_turn_start(boundary):
        return {'first_kept_index': cut, 'turn_start_index': -1, 'is_split_turn': False}
    turn_start = -1
    for j in range(cut, -1, -1):
        if _is_turn_start(messages[j]):
            turn_start = j
            break
    return {'first_kept_index': cut, 'turn_start_index': turn_start,
            'is_split_turn': turn_start != -1}


def _is_compaction_entry(message: dict) -> bool:
    return bool(message.get('is_compaction'))


def prepare_compaction(messages: list[dict], settings: CompactionSettings) -> dict | None:
    """纯函数准备：定位边界、切点、待摘要区与轮前缀区；无需压缩返回 None。"""
    if messages and _is_compaction_entry(messages[-1]):
        return None
    prev_index = -1
    previous_summary = None
    for index, message in enumerate(messages):
        if _is_compaction_entry(message):
            prev_index = index
            previous_summary = message.get('summary')
    boundary_start = prev_index + 1
    cut = find_cut_point(messages, settings.keep_recent_tokens)
    first_kept = max(cut['first_kept_index'], boundary_start)
    history_end = cut['turn_start_index'] if cut['is_split_turn'] else first_kept
    history_end = max(history_end, boundary_start)
    messages_to_summarize = [
        m for m in messages[boundary_start:history_end] if m.get('role') != 'system']
    turn_prefix_messages = []
    if cut['is_split_turn'] and cut['turn_start_index'] >= boundary_start:
        turn_prefix_messages = [
            m for m in messages[cut['turn_start_index']:first_kept] if m.get('role') != 'system']
    if not messages_to_summarize and not turn_prefix_messages:
        return None
    return {'first_kept_index': first_kept,
            'messages_to_summarize': messages_to_summarize,
            'turn_prefix_messages': turn_prefix_messages,
            'is_split_turn': cut['is_split_turn'],
            'tokens_before': estimate_context_tokens(messages)['tokens'],
            'previous_summary': previous_summary}


async def compact(preparation: dict, summarize) -> dict:
    """执行压缩：注入式异步摘要器，split turn 时主摘要+轮前缀两次调用合并。

    摘要器异常向上透传——生产端把截断/错误摘要转为异常即实现
    「残缺文本不得成为会话检查点」的拒落盘纪律。
    """
    messages_to_summarize = preparation['messages_to_summarize']
    turn_prefix = preparation['turn_prefix_messages']
    previous = preparation.get('previous_summary')
    if preparation.get('is_split_turn') and turn_prefix:
        summary = previous if messages_to_summarize == [] and previous else None
        if summary is None:
            summary = await summarize(messages_to_summarize, previous) if messages_to_summarize \
                else (previous or '暂无可摘要的前情。')
        prefix = await summarize(turn_prefix, None)
        summary = f'{summary}\n\n---\n\n**Turn Context (split turn):**\n\n{prefix}'
    else:
        summary = await summarize(messages_to_summarize, previous)
    return {'summary': summary,
            'first_kept_index': preparation['first_kept_index'],
            'tokens_before': preparation['tokens_before']}


def build_post_compaction_messages(messages: list[dict], result: dict) -> list[dict]:
    """组装压缩后的新会话形态：摘要条目带头 + 保留区消息拷贝(剥离 usage)。

    保留区旧 usage 是压缩前大上下文的实报，重排后当新锚会误判二次压缩
    (P4 修⑥a 案)——剥离后计量退回 chars/3 估算，直到下一次 provider 实报。
    剥离作用于拷贝，不回改原会话。
    """
    checkpoint = {'role': 'system', 'content': result['summary'],
                  'is_compaction': True, 'summary': result['summary']}
    kept = []
    for message in messages[result['first_kept_index']:]:
        copied = {key: value for key, value in message.items() if key != 'usage'}
        kept.append(copied)
    return [checkpoint, *kept]


# 六节结构化摘要模板(设计稿 §3.2)；Nai 本地化=「保精确引用」写成
# 保章号/设定账本键/剧情指针——压缩不丢设定与剧情锚点。
SUMMARIZATION_PROMPT = '''The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the author trying to accomplish?]

## Constraints & Preferences
- [Constraints, preferences, or requirements mentioned by author, or "(none)"]

## Progress
### Done
- [x] [Completed chapters/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, or "(none)"]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [设定账本键(事实/实体/大纲节点)、章号、剧情指针——必须原样保留精确引用]
- [Any data or references needed to continue, or "(none)"]

Keep each section concise. Preserve exact chapter numbers, story-bible keys, and plot pointers.'''

UPDATE_INSTRUCTIONS = '''Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- PRESERVE exact chapter numbers, story-bible keys, and plot pointers
- If something is no longer relevant, you may remove it

Use the same EXACT format as before.'''


def _serialize_messages(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        role = message.get('role', '?')
        content = message.get('content') or ''
        lines.append(f'[{role}] {content}')
    return '\n'.join(lines)


def make_provider_summarizer(provider, *, max_tokens: int | None = None):
    """构造注入 compact() 的生产摘要器：六节模板+增量更新+失败纪律。

    stopReason 为 error/length 的摘要抛错——「残缺文本不得成为会话
    检查点」，compact 透传即拒落盘。
    """

    async def summarize(messages: list[dict], previous_summary, custom_instructions=None):
        prompt = f'<conversation>\n{_serialize_messages(messages)}\n</conversation>\n\n'
        if previous_summary:
            prompt += f'<previous-summary>\n{previous_summary}\n</previous-summary>\n\n' + UPDATE_INSTRUCTIONS
        else:
            prompt += SUMMARIZATION_PROMPT
        if custom_instructions:
            prompt += f'\n\nAdditional focus: {custom_instructions}'
        response = await provider.complete(
            [{'role': 'user', 'content': prompt}], max_tokens=max_tokens)
        if response.stop_reason == 'error':
            raise RuntimeError(f'Summarization failed: {response.error_message or "Unknown error"}')
        if response.stop_reason == 'length':
            raise RuntimeError('Summarization failed: generation hit the token cap and the summary is incomplete')
        return response.text

    return summarize
