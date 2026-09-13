"""显式创作任务与独立输出契约，结构化任务不经过正文生成 Prompt。"""
import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from app.models.schemas import GenerationRequest
from app.services.context_budget import (
    MAX_CHAT_OUTPUT_CHARS, MAX_GENERATION_PROMPT_CHARS, MAX_REVIEW_CONTENT_CHARS,
    MAX_STORY_CONTEXT_CHARS, compact_text,
)
from app.services.model_result import ModelOutputError, parse_model_result
from app.services.writing_execution import invoke_model


WritingMode = Literal['discuss', 'continue', 'advanced_continue', 'rewrite', 'outline', 'character', 'check', 'new_chapter']


class TaskOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_length: int = Field(500, ge=100, le=3000)
    # 这是单次模型请求能稳定产出的近段规划量，不是作品篇幅上限。
    target_chapters: int = Field(10, ge=1, le=200)
    character_type: str = Field('主要角色', min_length=1, max_length=20)
    current_day: int | None = Field(None, gt=0)


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class OutlineChapter(StrictOutput):
    chapter_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    plot_points: list[str] = Field(min_length=1, max_length=8)

    @field_validator('plot_points')
    @classmethod
    def bounded_points(cls, points):
        if any(not p.strip() or len(p) > 500 for p in points):
            raise ValueError('情节点必须为1至500字符')
        return points


class OutlineOutput(StrictOutput):
    chapters: list[OutlineChapter] = Field(min_length=1, max_length=200)


class CharacterOutput(StrictOutput):
    name: str = Field(min_length=1, max_length=100)
    appearance: str = Field(min_length=1, max_length=1000)
    personality: str = Field(min_length=1, max_length=1000)
    background: str = Field(min_length=1, max_length=2000)
    abilities: list[str] = Field(max_length=20)
    motivation: str = Field(min_length=1, max_length=1000)
    relationships: list[str] = Field(max_length=20)

    @field_validator('abilities', 'relationships')
    @classmethod
    def bounded_items(cls, items):
        if any(not item.strip() or len(item) > 500 for item in items):
            raise ValueError('条目必须为1至500字符')
        return items


class CheckIssue(StrictOutput):
    category: Literal['剧情', '人物', '世界观', '语言', '时间线']
    message: str = Field(min_length=1, max_length=1000)
    quote: str = Field(min_length=1, max_length=500)


class CheckOutput(StrictOutput):
    summary: str = Field(min_length=1, max_length=1000)
    issues: list[CheckIssue] = Field(max_length=20)
    suggestions: list[str] = Field(max_length=20)

    @field_validator('suggestions')
    @classmethod
    def bounded_suggestions(cls, items):
        if any(not item.strip() or len(item) > 500 for item in items):
            raise ValueError('建议必须为1至500字符')
        return items


class NewChapterOutput(StrictOutput):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_CHAT_OUTPUT_CHARS)

    @field_validator('title', 'content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('章节标题与正文不能为空')
        return value.strip()


class AgentProjectInfoAction(StrictOutput):
    """Agent 判断需要更新项目信息时给出的动作。"""
    kind: Literal['project_info']
    genre: str | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=8_000)
    worldview: str | None = Field(None, max_length=50_000)


class AgentEntityAction(StrictOutput):
    """Agent 判断出现需要长期跟踪的实体时给出的动作。"""
    kind: Literal['entity']
    name: str = Field(min_length=1, max_length=100)
    entity_kind: Literal['character', 'item', 'location', 'organization']
    description: str = Field(min_length=1, max_length=500)


class AgentFactAction(StrictOutput):
    """Agent 判断出现可核对设定事实时给出的动作。"""
    kind: Literal['fact']
    subject: str = Field(min_length=1, max_length=100)
    attribute: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)


class AgentOutlineAction(StrictOutput):
    """Agent 判断需要补结构时给出的卷/章计划。"""
    kind: Literal['outline']
    node_kind: Literal['volume', 'chapter']
    title: str = Field(min_length=1, max_length=200)
    chapter_number: int | None = Field(None, gt=0)
    summary: str = Field(min_length=1, max_length=1000)


AgentAction = Annotated[
    Union[AgentProjectInfoAction, AgentEntityAction, AgentFactAction, AgentOutlineAction],
    Field(discriminator='kind'),
]

AgentActionAdapter = TypeAdapter(AgentAction)


class AgentManuscript(BaseModel):
    """Agent 判断这一轮该直接起草正文时给出的稿件。"""
    model_config = ConfigDict(extra='forbid')
    operation: Literal['append', 'rewrite', 'create']
    content: str = Field(min_length=1, max_length=MAX_CHAT_OUTPUT_CHARS)
    title: str | None = Field(None, max_length=200)


class AgentReplyOutput(StrictOutput):
    """Agent 每一轮的输出：回复、设定动作，以及它自己判断要不要起草的正文。"""
    reply: str = Field(min_length=1, max_length=MAX_CHAT_OUTPUT_CHARS)
    actions: list[AgentAction] = Field(default_factory=list, max_length=30)
    manuscript: AgentManuscript | None = None
    uncertainties: list[str] = Field(default_factory=list, max_length=20)


_AGENT_OPERATION = {'append': 'append', 'rewrite': 'replace', 'create': 'create'}
_AGENT_MODE = {'append': 'continue', 'rewrite': 'rewrite', 'create': 'new_chapter'}


def _parse_agent_reply(text: str) -> tuple[str, dict | None, str | None, str | None]:
    """解析 Agent 回复。

    模型输出天然会有波动，任何一段不合格都不该让作者看到原始 JSON。
    严格解析失败时逐项降级：保住回复文本，能用的动作照常保留。
    """
    candidate = text.strip()
    start, end = candidate.find('{'), candidate.rfind('}') + 1
    if start < 0 or end <= start:
        return text, None, None, None
    try:
        raw = json.loads(candidate[start:end])
    except ValueError:
        return text, None, None, None
    if not isinstance(raw, dict):
        return text, None, None, None

    reply = raw.get('reply') if isinstance(raw.get('reply'), str) else None
    if not reply or not reply.strip():
        return text, None, None, None
    reply = reply.strip()[:MAX_CHAT_OUTPUT_CHARS]

    actions: list[dict] = []
    for item in raw.get('actions') or []:
        if not isinstance(item, dict):
            continue
        try:
            actions.append(AgentActionAdapter.validate_python(item).model_dump())
        except ValidationError:
            continue

    manuscript = None
    operation = None
    decided = None
    raw_manuscript = raw.get('manuscript')
    if isinstance(raw_manuscript, dict):
        try:
            parsed_manuscript = AgentManuscript.model_validate(raw_manuscript)
        except ValidationError:
            parsed_manuscript = None
        if parsed_manuscript is not None:
            manuscript = parsed_manuscript
            operation = _AGENT_OPERATION[parsed_manuscript.operation]
            decided = _AGENT_MODE[parsed_manuscript.operation]

    uncertainties = [item.strip()[:500] for item in (raw.get('uncertainties') or [])
                     if isinstance(item, str) and item.strip()][:20]

    if manuscript is not None:
        payload = {'reply': reply, 'actions': actions,
                   'manuscript': manuscript.model_dump(),
                   'uncertainties': uncertainties, 'decided_mode': decided}
        return manuscript.content, payload, operation, decided
    if not actions and not uncertainties:
        return reply, None, None, None
    return reply, {'reply': reply, 'actions': actions, 'uncertainties': uncertainties,
                   'decided_mode': 'discuss'}, None, 'discuss'


@dataclass
class TaskResult:
    text: str
    result: dict | None = None
    operation: str | None = None


AGENT_DESCRIPTION = """你是 Nai 的创作 Agent。作者在和你自由交流这部小说，你负责回应，并自行判断这一轮里有没有需要落库的设定。

你有四类可以提议的动作，但你只能提议，不能自己写入；作者确认后系统才会落库：
- project_info：更新项目类型、简介或世界观。只在作者这次确实给出或修改了这些内容时才用。
- entity：出现需要长期跟踪的人物、物品、地点或组织。
- fact：出现可核对的设定事实，例如人物身份、位置、持有物、关系、世界规则。
- outline：需要补卷/阶段或某一章的计划。

作者不需要先声明"这是续写还是讨论"，由你从他的话里判断：
- 他只是提问、讨论写法或聊设定时，正常回答，actions 和 manuscript 都留空。
- 他让你接着写、往下写、写下一段时，用 manuscript 给出正文，operation 用 append。
- 他让你改这一章时，用 manuscript 给出改写后的整章，operation 用 rewrite。
- 他让你开新的一章时，用 manuscript 给出新章正文和 title，operation 用 create。
- 同一轮里既涉及设定又需要写正文时，可以同时给 actions 和 manuscript。

判断原则：
1. 作者只是在提问、讨论写法或闲聊时，actions 留空，正常回答即可。
2. 作者说出新的设定、修改设定或明确要求你整理设定时，才给出对应动作。
3. 作者没说的不要编造。可以保守补全，但必须写进 uncertainties。
4. project_info 里只给这次确实涉及或需要补全的字段，其余留 null，不要凭空重写已有内容。
5. 同一个实体不要重复提议；已经在设定账本里的只做必要更新。
6. manuscript 里的正文必须是完整可用的稿件，不要写占位或省略。

只输出严格 JSON，不要 Markdown、解释或代码围栏，结构必须符合：
{schema}
"""


async def execute_task(*, mode: WritingMode, service, context_pack, current_content: str,
                       instruction: str, history, options: TaskOptions, novel_id: int,
                       actor_id: int, novel_lifecycle_id: str, target_chapter: int,
                       project_meta: dict | None = None) -> TaskResult:
    """工具由枚举明确选择；模型不能自行执行写库、采纳或其他工具。"""
    if mode == 'discuss':
        # 交流就是 Agent：作者只负责说，由模型自己判断这一轮要不要提议写设定。
        meta = project_meta or {}
        messages = service.prepare_messages(context_pack=context_pack, current_content=current_content,
                                            turns=history, instruction=instruction, mode='discuss')
        # 追加到既有 system 契约，保持当前正文/历史仍在原位置。
        messages[0] = ('system', messages[0][1] + '\n\n' + AGENT_DESCRIPTION.replace(
            '{schema}', json.dumps(AgentReplyOutput.model_json_schema(), ensure_ascii=False))
            + '\n当前项目信息（未填写表示暂无）：\n'
            + f"类型：{meta.get('genre') or '未填写'}\n简介：{meta.get('description') or '未填写'}")
        raw = await invoke_model(service.llm, messages)
        output = parse_model_result(raw, max_output_chars=MAX_CHAT_OUTPUT_CHARS)
        text, payload, operation, _decided = _parse_agent_reply(output.text)
        return TaskResult(text, payload, operation)
    if mode == 'continue':
        messages = service.prepare_messages(context_pack=context_pack, current_content=current_content,
                                            turns=history, instruction=instruction, mode=mode)
        output = await service.reply(messages)
        return TaskResult(output.text, operation='append')
    if mode == 'advanced_continue':
        from app.services.agent_service import agent_service
        prompt = compact_text('前文末段：\n' + compact_text(current_content, MAX_STORY_CONTEXT_CHARS, keep='tail')
                              + '\n续写要求：\n' + instruction, MAX_GENERATION_PROMPT_CHARS, keep='both')
        response = await agent_service.generate_content(
            GenerationRequest(novel_id=novel_id, chapter=target_chapter, prompt=prompt,
                              current_day=options.current_day, target_length=options.target_length),
            actor_id=actor_id, novel_lifecycle_id=novel_lifecycle_id,
        )
        return TaskResult(response.final_content, {
            'final_consistency': response.final_consistency.model_dump(),
            'workflow_trace': response.workflow_trace.model_dump(mode='json') if response.workflow_trace else None,
            'context_manifest': response.context_manifest,
        }, 'append')
    if mode in {'rewrite', 'check'} and len(current_content) > MAX_REVIEW_CONTENT_CHARS:
        raise ValueError(f'整章{mode}目前最多支持{MAX_REVIEW_CONTENT_CHARS}字符，请使用局部工具。')
    # 改写和检查必须看到完整被处理文本，不能把裁剪后的尾段冒充整章。
    source = compact_text(current_content, MAX_REVIEW_CONTENT_CHARS if mode in {'rewrite', 'check'} else MAX_STORY_CONTEXT_CHARS, keep='tail')
    descriptions = {
        'rewrite': '重写作者提供的整段正文，保留事件和设定。只返回改写正文，不要解释。',
        'outline': f'生成恰好 {options.target_chapters} 章的结构化大纲。只返回 JSON：{{"chapters":[{{"chapter_number":1,"title":"标题","plot_points":["情节点"]}}]}}。章号从1连续递增。',
        'character': f'设计一个{options.character_type}。只返回 JSON，字段必须为 name、appearance、personality、background、abilities（字符串数组）、motivation、relationships（字符串数组）。',
        'check': '审阅正文并给出可核对的问题。只返回 JSON：{"summary":"审核说明","issues":[{"category":"剧情或人物或世界观或语言或时间线","message":"问题","quote":"正文逐字引用"}],"suggestions":["建议"]}。不要捏造引用；没有发现问题时 issues 为空。这只是模型建议，不是自动发布许可。',
        'new_chapter': f'创作下一章约{options.target_length}字的初稿。只返回 JSON：{{"title":"章节标题","content":"章节正文"}}。这是待作者确认的候选，不代表已经写入小说。',
    }
    messages = service.prepare_messages(context_pack=context_pack, current_content='', turns=[],
                                        instruction=instruction, mode='discuss')
    messages.insert(0, ('system', descriptions[mode]))
    messages.append(('user', '本次待处理原文或参考正文：\n' + source))
    raw = await invoke_model(service.llm, messages)
    output = parse_model_result(raw, max_output_chars=MAX_CHAT_OUTPUT_CHARS)
    if mode == 'rewrite':
        return TaskResult(output.text, operation='replace')
    schema = {'outline': OutlineOutput, 'character': CharacterOutput, 'check': CheckOutput, 'new_chapter': NewChapterOutput}[mode]
    try:
        parsed = schema.model_validate_json(output.text)
        if mode == 'outline' and [chapter.chapter_number for chapter in parsed.chapters] != list(range(1, options.target_chapters + 1)):
            raise ValueError('大纲数量或章号不符合请求')
        if mode == 'check' and any(issue.quote not in current_content for issue in parsed.issues):
            raise ValueError('审核引用不在原文中')
    except (ValueError, ValidationError) as exc:
        raise ModelOutputError('invalid_task_output', '模型没有返回符合当前任务结构的完整结果，请重新生成。') from exc
    payload = parsed.model_dump()
    if mode == 'outline':
        text = '\n\n'.join(f"第{chapter.chapter_number}章 {chapter.title}\n" + '\n'.join('- ' + point for point in chapter.plot_points) for chapter in parsed.chapters)
    elif mode == 'character':
        text = f'{parsed.name}\n\n外貌：{parsed.appearance}\n性格：{parsed.personality}\n背景：{parsed.background}\n能力：' + '、'.join(parsed.abilities) + f'\n动机：{parsed.motivation}\n关系：' + '、'.join(parsed.relationships)
    elif mode == 'check':
        from app.services.agent_service import AgentService
        from app.services.consistency_service import consistency_service
        reference = await asyncio.to_thread(AgentService._load_consistency_reference_sync,
            novel_id, actor_id, novel_lifecycle_id, target_chapter, options.current_day)
        payload['consistency'] = await consistency_service.check_content(
            novel_id=novel_id, content=current_content, chapter=target_chapter,
            current_day=options.current_day, reference=reference)
        payload['advisory_only'] = True
        text = parsed.summary + '\n\n' + '\n'.join(f'- {issue.category}：{issue.message}（原文：{issue.quote}）' for issue in parsed.issues)
    else:
        text = parsed.content
    return TaskResult(text, payload, 'create' if mode == 'new_chapter' else None)
