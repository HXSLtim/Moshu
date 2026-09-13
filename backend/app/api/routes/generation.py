"""
内容生成路由
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.models.schemas import (
    GenerationRequest,
    GenerationResponse,
    InitNovelRequest,
    InitNovelResponse,
    PlotOptionsRequest,
    PlotOptionsResponse,
    PlotOption,
    AutoChapterRequest,
    ChapterNextCreate,
    ChapterResponse,
    RewriteRequest,
    RewriteResponse,
    IdeaParseRequest,
    IdeaParseResponse,
)
from app.services.agent_service import agent_service
from app.services.rag_service import rag_service
from app.db.base import get_db
from app.crud import novel as novel_crud
from app.api.dependencies import get_current_user
from app.models.user import User
from pydantic import BaseModel, Field
from typing import Literal
from loguru import logger
from app.services.model_provider import create_chat_model
from app.services.model_result import parse_model_result
from app.services.writing_execution import execution_scope, invoke_model
from app.services.writing_jobs import (durable_route, register_handler, submit_job, dispatch_job,
    owned_job, stop_job, reconcile_jobs, submit_legacy_job)
from app.models.writing_chat import WritingGenerationJob
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import ConfigDict, ValidationError
from app.services.writing_tasks import TaskOptions, execute_task
from app.services.writing_service import writing_service
from app.services.writing_proposals import create_proposal
from app.models.writing_schemas import ProposalResponse
from app.services.context_builder import build_context_pack
from types import SimpleNamespace
from langchain.prompts import ChatPromptTemplate
from app.core.config import settings
import json
import asyncio
from app.services.context_budget import (
    MAX_CHAT_OUTPUT_CHARS,
    MAX_CURRENT_CONTENT_CHARS,
    MAX_GENERATION_PROMPT_CHARS,
    MAX_PLOT_HINT_CHARS,
    MAX_STORY_CONTEXT_CHARS,
    MAX_WORLDVIEW_CONTEXT_CHARS,
    compact_text,
    ensure_generation_prompt_budget,
)

router = APIRouter()


# 初始化设定使用的LLM
init_llm = create_chat_model(
    max_retries=0,
    model=settings.OPENAI_MODEL_COMPLEX,
    temperature=0.8,
    max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
)


class ContinueRequest(BaseModel):
    """章节续写请求"""
    novel_id: int = Field(..., gt=0)
    chapter_id: int = Field(..., gt=0)
    current_content: str = Field(..., max_length=MAX_CURRENT_CONTENT_CHARS)
    expected_novel_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    expected_chapter_lifecycle_id: str | None = Field(None, min_length=32, max_length=32)
    target_length: int = Field(500, ge=100, le=3000)
    current_day: int | None = Field(None, gt=0, description="故事当前天数；未知时只按章节限定上下文")
    # 用户可控参数
    style_strength: float = Field(0.7, ge=0, le=1)  # 文风强度 (0-1)
    pace: Literal["slow", "medium", "fast"] = "medium"
    tone: Literal["neutral", "tense", "relaxed", "sad", "joyful"] = "neutral"
    use_rag_style: bool = True  # 是否使用RAG学习文风
    style_sample_id: int | None = None  # 文风样本ID（用户上传的参考文风）
    plot_direction_hint: str | None = Field(None, max_length=MAX_PLOT_HINT_CHARS)


class OutlineRequest(BaseModel):
    """大纲生成请求"""
    novel_id: int = Field(..., gt=0)
    theme: str = Field(..., min_length=1, max_length=1000)
    target_chapters: int = Field(10, ge=1, le=200)


class CharacterRequest(BaseModel):
    """角色生成请求"""
    novel_id: int = Field(..., gt=0)
    character_type: str = Field(..., min_length=1, max_length=20)
    character_description: str = Field(..., min_length=1, max_length=1000)


@router.post("/parse-idea", response_model=IdeaParseResponse)
async def parse_idea(
    request: IdeaParseRequest,
    current_user: User = Depends(get_current_user),
):
    """把作者的一段自然语言想法解析为可编辑的建书草案，不提前写入小说。

    长篇按两层规划：全书用卷/阶段覆盖，只有开头若干章列逐章大纲。
    这样几百上千章的作品不必依赖一次模型输出，也不会给作者一个虚假的章节上限。
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是 Nai 的建书策划 Agent。作者只会告诉你一段自然语言想法，你负责把它整理成可编辑的小说初始化草案。

只使用作者明确说出的信息；缺失内容可以做保守的创作补全，但必须把不确定点放入 uncertainties，不能把猜测写成作者事实。

规划按两层进行：
1. arcs 是全书卷/阶段结构，3 到 8 条，chapter_start/chapter_end 必须连续无缝覆盖第 1 章到第 {planned_chapters} 章，用于支撑长篇。
2. opening_outline 只详列开头可直接开写的章节，最多 8 章，chapter_number 从 1 连续递增。

不要把整本书压缩成开头几章，也不要逐章展开全书。计划大纲属于 planned，不代表已经发生。
角色必须拆成独立对象，剧情线索单独列出。
planned_chapters 必须回填作者给出的全书预计章数。
只输出严格 JSON，不要 Markdown、解释或代码围栏。JSON 必须符合这个 Schema：
{schema}
"""),
        ("user", "全书预计章数：{planned_chapters}\n作者的想法：{idea}"),
    ])
    try:
        chain = prompt | init_llm
        raw = parse_model_result(await invoke_model(chain, {
            "planned_chapters": request.planned_chapters,
            "idea": request.idea.strip(),
            "schema": json.dumps(IdeaParseResponse.model_json_schema(), ensure_ascii=False),
        }), max_output_chars=MAX_CHAT_OUTPUT_CHARS).text
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("模型未返回 JSON")
        result = IdeaParseResponse.model_validate_json(raw[start:end])
        if result.planned_chapters != request.planned_chapters:
            raise ValueError("模型回填的全书篇幅与请求不一致")
        expected_start = 1
        for arc in result.arcs:
            if arc.chapter_start != expected_start or arc.chapter_end < arc.chapter_start:
                raise ValueError("卷/阶段没有连续覆盖全书")
            expected_start = arc.chapter_end + 1
        if expected_start != request.planned_chapters + 1:
            raise ValueError("卷/阶段没有覆盖到全书最后一章")
        numbers = [item.chapter_number for item in result.opening_outline]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("开头章节大纲的章号不连续")
        return result
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="AI 未返回完整的结构化建书草案，请换一种说法重试") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI 解析作者想法失败")
        raise HTTPException(status_code=502, detail="AI 暂时无法解析这段想法，请稍后重试") from exc


@router.post("/init", response_model=InitNovelResponse)
@durable_route('init')
async def init_novel(
    request: InitNovelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 初始化小说设定

    根据小说的标题、类型和用户提供的主题，自动生成世界观、主要角色、大纲和剧情线索。
    """
    try:
        logger.info(
            "AI初始化小说设定：novel_id={}, target_chapters={}, theme_length={}",
            request.novel_id,
            request.target_chapters,
            len(request.theme or ""),
        )
        # 校验小说归属
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")
        if not 1 <= request.target_chapters <= 80:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="目标章节数必须在 1 到 80 之间",
            )

        # 构造提示词（注意：示例JSON中的花括号需要用双花括号转义，避免被当作模板变量）
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是一名专业的中文网络小说策划编辑，擅长根据简单的想法，生成完整的设定与大纲。

请你根据用户提供的信息，为这部小说生成：
- 世界观设定（worldview）：整体世界结构、力量体系、时代背景等，使用多段文字描述；
- 主要角色列表（main_characters）：3-6个主要角色，每个用一句话概括；
- 故事大纲（outline）：从开篇到结局的主线设计，可以按段落分点描述；
- 剧情线索（plot_hooks）：3-8条可以展开的重要伏笔或矛盾。

输出时请严格使用JSON格式（注意：下面是结构示例，不是内容）：
{{
  "worldview": "...",
  "main_characters": ["角色1：...", "角色2：..."],
  "outline": "...",
  "plot_hooks": ["线索1", "线索2", "线索3"]
}}

不要输出任何解释性文字、注释或前后缀，只输出上述JSON。""",
                ),
                (
                    "user",
                    """小说标题：{title}
小说类型：{genre}
已有简介：{description}
目标章节数：{target_chapters}
故事主题/补充说明：{theme}
""",
                ),
            ]
        )

        chain = prompt | init_llm
        result = await invoke_model(chain,
            {
                "title": novel.title,
                "genre": novel.genre or "未指定",
                "description": compact_text(
                    novel.description,
                    MAX_STORY_CONTEXT_CHARS,
                    keep="head",
                ) or "暂无简介",
                "target_chapters": request.target_chapters,
                "theme": compact_text(request.theme, 1000, keep="head"),
            }
        )

        raw = parse_model_result(result, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text

        try:
            # 尝试从返回内容中提取JSON片段
            start = raw.find("{")
            end = raw.rfind("}") + 1
            json_str = raw[start:end] if start != -1 and end != 0 else raw
            data = json.loads(json_str)
        except Exception as e:  # noqa: BLE001
            logger.error(f"解析初始化设定JSON失败: {e}")
            raise HTTPException(status_code=500, detail="AI返回格式异常，初始化设定失败")

        worldview = str(data.get("worldview") or "").strip()
        main_chars_raw = data.get("main_characters") or data.get("characters") or []
        outline = str(data.get("outline") or "").strip()
        plot_hooks_raw = data.get("plot_hooks") or []

        # 规范化 main_characters
        if isinstance(main_chars_raw, str):
            main_characters = [line.strip() for line in main_chars_raw.split("\n") if line.strip()]
        elif isinstance(main_chars_raw, list):
            main_characters = [str(item).strip() for item in main_chars_raw if str(item).strip()]
        else:
            main_characters = []

        # 规范化 plot_hooks
        if isinstance(plot_hooks_raw, str):
            plot_hooks = [line.strip() for line in plot_hooks_raw.split("\n") if line.strip()]
        elif isinstance(plot_hooks_raw, list):
            plot_hooks = [str(item).strip() for item in plot_hooks_raw if str(item).strip()]
        else:
            plot_hooks = []

        return InitNovelResponse(
            novel_id=request.novel_id,
            worldview=worldview,
            main_characters=main_characters,
            outline=outline,
            plot_hooks=plot_hooks,
        )

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"AI初始化小说设定失败: {e}")
        raise HTTPException(status_code=500, detail=f"初始化设定失败: {str(e)}")


@router.post("/generate", response_model=GenerationResponse)
@durable_route('generate')
async def generate_content(
    request: GenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    生成小说内容

    使用三Agent协作工作流生成高质量小说段落：
    - Agent A：世界观描写
    - Agent B：角色对话
    - Agent C：剧情控制

    Args:
        request: 生成请求

    Returns:
        生成响应（包含最终内容和各Agent输出）

    Raises:
        HTTPException: 生成失败时抛出
    """
    try:
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        try:
            ensure_generation_prompt_budget(request.prompt)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        logger.info(
            "收到生成请求：小说{}，章节{}，提示词长度={}",
            request.novel_id,
            request.chapter,
            len(request.prompt),
        )
        response = await agent_service.generate_content(
            request, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id,
        )
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"生成失败: {str(e)}"
        )


@router.post("/plot-options", response_model=PlotOptionsResponse)
@durable_route('plot_options')
async def generate_plot_options(
    request: PlotOptionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成剧情走向选项

    用于在续写前给用户提供多个可选的剧情发展方向，由AI给出结构化描述。
    """
    try:
        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 验证章节归属
        chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
        if not chapter or chapter.novel_id != request.novel_id:
            raise HTTPException(status_code=404, detail="章节不存在")

        # 构造提示词
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """你是一名专业的小说剧情策划编辑。

你的任务是根据小说的设定、当前章节内容和整体节奏，设计多个合理的下一步剧情走向选项。

要求：
1. 不要直接给出续写正文，只输出剧情走向的结构化描述。
2. 每个选项需要包含：title（简短标题）、summary（具体会发生什么）、impact（对节奏/情绪/伏笔的影响，简要），risk（潜在风险，可选）。
3. 输出必须是JSON格式：{{"options": [{{"title": "...", "summary": "...", "impact": "...", "risk": "..."}}, ...]}}。
4. 不要添加任何额外说明或前后缀，只输出JSON。
""",
            ),
            (
                "user",
                """请基于以下信息给出{num_options}个下一步剧情走向选项：

小说标题：{title}
小说类型：{genre}
世界观（节选）：{worldview}
故事简介：{description}

当前章节标题：{chapter_title}
当前章节内容（节选）：{chapter_excerpt}

当前写作内容（用于判断下一步剧情）：{current_excerpt}
""",
            ),
        ])

        # 构造章节与当前内容节选，避免提示过长
        chapter_excerpt = chapter.content[-500:] if len(chapter.content) > 500 else chapter.content
        current_excerpt = (
            request.current_content[-800:]
            if len(request.current_content) > 800
            else request.current_content
        )
        worldview_excerpt = (
            novel.worldview[:500] + "..." if novel.worldview and len(novel.worldview) > 500 else (novel.worldview or "未设定")
        )

        chain = prompt | init_llm
        response = await invoke_model(chain,
            {
                "num_options": request.num_options,
                "title": novel.title,
                "genre": novel.genre or "未指定",
                "worldview": worldview_excerpt,
                "description": novel.description or "暂无简介",
                "chapter_title": chapter.title,
                "chapter_excerpt": chapter_excerpt or "暂无内容",
                "current_excerpt": current_excerpt or "",
            }
        )

        raw = parse_model_result(response, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text

        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            json_str = raw[start:end] if start != -1 and end != 0 else raw
            data = json.loads(json_str)
            options_raw = data.get("options", [])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"解析剧情选项JSON失败，将原始内容作为单个选项返回: {e}")
            options_raw = [
                {
                    "title": "默认剧情走向",
                    "summary": raw,
                    "impact": "",
                    "risk": "",
                }
            ]

        options: list[PlotOption] = []
        for idx, item in enumerate(options_raw[: request.num_options], start=1):
            title = str(item.get("title") or f"剧情选项{idx}")
            summary = str(item.get("summary") or "")
            impact = item.get("impact")
            risk = item.get("risk")

            options.append(
                PlotOption(
                    id=idx,
                    title=title,
                    summary=summary,
                    impact=str(impact) if impact is not None else None,
                    risk=str(risk) if risk is not None else None,
                )
            )

        response = PlotOptionsResponse(
            novel_id=request.novel_id,
            chapter_id=request.chapter_id,
            options=options,
        )
        logger.info(
            "生成剧情选项完成：novel_id={}, chapter_id={}, 实际返回选项数={}",
            response.novel_id,
            response.chapter_id,
            len(response.options),
        )
        return response

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"生成剧情选项失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成剧情选项失败: {str(e)}")


def _validate_source_identity(request, novel, chapter=None):
    expected_novel = getattr(request, 'expected_novel_lifecycle_id', None)
    expected_chapter = getattr(request, 'expected_chapter_lifecycle_id', None)
    if expected_novel is not None and expected_novel != novel.rag_lifecycle_id:
        raise HTTPException(409, '小说来源已变化，请重新打开作品')
    if expected_chapter is not None and (chapter is None or expected_chapter != chapter.rag_lifecycle_id):
        raise HTTPException(409, '章节来源已变化，请重新打开章节')


async def _run_structured_task(db, novel, *, mode, instruction, options, current_content='', target_chapter=1):
    """独立工具与主对话共享契约，任何来源变化均不发布结果。"""
    novel_id, actor_id, lifecycle = novel.id, novel.user_id, novel.rag_lifecycle_id
    pack = build_context_pack(db, novel_id=novel_id, actor_id=actor_id,
        novel_lifecycle_id=lifecycle, target_chapter=target_chapter, current_day=options.current_day, task=mode)
    db.commit()
    async with execution_scope(max_model_calls=1) as meter:
        result = await execute_task(mode=mode, service=writing_service, context_pack=pack,
            current_content=current_content, instruction=instruction, history=[], options=options,
            novel_id=novel_id, actor_id=actor_id, novel_lifecycle_id=lifecycle, target_chapter=target_chapter,
            project_meta={'genre': novel.genre, 'description': novel.description})
    db.expire_all()
    current = novel_crud.get_novel_by_id(db, novel_id)
    if current is None or current.user_id != actor_id or current.rag_lifecycle_id != lifecycle:
        raise HTTPException(409, '小说来源已经改变，请重新生成')
    return result, pack, meter.snapshot()


@router.post("/auto-chapter", response_model=ProposalResponse)
@durable_route('auto_chapter')
async def auto_create_chapter(
    request: AutoChapterRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """生成持久的新章候选；作者通过候选确认接口决定是否创建章节。"""
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(404, '小说不存在或无权访问')
    base = novel_crud.get_chapter_by_id(db, request.base_chapter_id) if request.base_chapter_id else novel_crud.get_latest_chapter(db, novel.id)
    if request.base_chapter_id and (base is None or base.novel_id != novel.id):
        raise HTTPException(404, '参考章节不存在或不属于本书')
    _validate_source_identity(request, novel, base)
    base_content = base.content if base else ''
    chapter_snapshot = SimpleNamespace(id=base.id, version=base.version, rag_lifecycle_id=base.rag_lifecycle_id) if base else None
    novel_snapshot = SimpleNamespace(id=novel.id, rag_lifecycle_id=novel.rag_lifecycle_id)
    actor_id = current_user.id
    target = novel_crud.get_max_chapter_number(db, novel.id) + 1
    try:
        result, pack, execution = await _run_structured_task(db, novel, mode='new_chapter',
            instruction=request.theme or '根据当前小说设定创作下一章。',
            options=TaskOptions(target_length=request.target_length), current_content=base_content, target_chapter=target)
        proposal = create_proposal(db, novel=novel_snapshot, actor_id=actor_id, chapter=chapter_snapshot,
            base_content=base_content, operation='create', content=result.text, title=result.result['title'],
            context_manifest=pack.manifest, execution=execution)
        db.commit()
        db.refresh(proposal)
        return proposal
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error('新章候选生成失败：{}', type(exc).__name__)
        raise HTTPException(500, '新章候选生成失败，请检查任务要求后重试') from exc


@router.post("/rewrite", response_model=RewriteResponse)
@durable_route('rewrite')
async def rewrite_text(
    request: RewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """局部文本改写

    根据用户选择的改写类型，对一小段文本进行润色/重写/压缩/扩写。
    """
    try:
        # 权限校验：至少校验小说归属
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        if not request.original_text.strip():
            raise HTTPException(status_code=400, detail="原文不能为空")

        source_snapshot = None
        chapter_snapshot = None
        selection_start = None
        novel_snapshot = SimpleNamespace(id=novel.id, rag_lifecycle_id=novel.rag_lifecycle_id)
        actor_id = current_user.id
        if request.chapter_id is not None:
            chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
            if not chapter or chapter.novel_id != request.novel_id:
                raise HTTPException(status_code=404, detail="章节不存在")
            start = getattr(request, 'selection_start', None)
            end = getattr(request, 'selection_end', None)
            if (start is None) != (end is None):
                raise HTTPException(422, '选区起止位置必须同时提供')
            if start is not None:
                if not 0 <= start < end <= len(chapter.content) or chapter.content[start:end] != request.original_text:
                    raise HTTPException(409, '选区原文与已保存版本不一致，请先保存后重试')
                selection_start = start
            else:
                selection_start = chapter.content.find(request.original_text)
                if selection_start < 0 or chapter.content.find(request.original_text, selection_start + 1) >= 0:
                    raise HTTPException(409, '请先保存正文，并选择可唯一定位的原文后重新改写')
            _validate_source_identity(request, novel, chapter)
            source_snapshot = chapter.content
            chapter_snapshot = SimpleNamespace(id=chapter.id, version=chapter.version, rag_lifecycle_id=chapter.rag_lifecycle_id)


        if request.chapter_id is None:
            _validate_source_identity(request, novel)

        # 改写类型说明
        type_map = {
            "polish": "在保持原始含义和大致长度不变的前提下，对文本进行润色，使其更流畅、生动、自然。",
            "rewrite": "在保持总体情节和信息不变的前提下，重新表述文本，可以调整句式和部分细节。",
            "shorten": "在保持关键信息和情感不变的前提下，将文本压缩得更加简洁短小。",
            "extend": "在保持原意的前提下，对文本进行扩写，补充分镜、环境或心理描写。",
        }
        rewrite_type = request.rewrite_type or "polish"
        type_desc = type_map.get(rewrite_type, type_map["polish"])

        style_hint = (request.style_hint or "").strip()
        style_part = f"\n风格提示：{style_hint}" if style_hint else ""

        length_part = ""
        if request.target_length is not None:
            length_part = f"\n目标字数：约{request.target_length}字（允许少量上下浮动）"

        user_prompt = f"""请根据以下要求改写这段中文文本：

改写类型：{type_desc}{style_part}{length_part}

【原文】
{request.original_text}

【输出要求】
1. 仅输出改写后的文本本身，不要解释原因，也不要添加额外的说明或前后缀。
2. 保持人物称呼、世界观名词等专有名词不变，避免引入与原文设定冲突的新设定。
"""

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """你是一名中文小说写作助手，擅长在保持含义和设定一致的前提下，对局部文本进行高质量改写。请严格按照用户要求进行改写，并且只输出改写后的文本本身。""",
                ),
                ("user", "{user_request}"),
            ]
        )

        chain = prompt | init_llm
        async with execution_scope(max_model_calls=1) as meter:
            result = await invoke_model(chain, {"user_request": user_prompt})
            rewritten = parse_model_result(result, max_output_chars=MAX_CHAT_OUTPUT_CHARS).text

        if not rewritten:
            raise HTTPException(status_code=500, detail="改写失败，模型返回为空")

        proposal_id = None
        if chapter_snapshot is not None:
            proposal = create_proposal(db, novel=novel_snapshot, actor_id=actor_id,
                chapter=chapter_snapshot, base_content=source_snapshot, operation='replace_selection',
                content=rewritten, execution=meter.snapshot(), selection_start=selection_start,
                selection_end=selection_start + len(request.original_text))
            db.commit()
            proposal_id = proposal.id
        return RewriteResponse(rewritten_text=rewritten, proposal_id=proposal_id, execution=meter.snapshot())

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"局部改写失败: {e}")
        raise HTTPException(status_code=500, detail=f"改写失败: {str(e)}")


@router.post("/continue")
@durable_route('continue')
async def continue_chapter(
    request: ContinueRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    章节续写：根据已有内容继续创作

    Args:
        request: 续写请求（包含当前内容和目标长度）
        current_user: 当前用户
        db: 数据库会话

    Returns:
        续写的内容
    """
    try:
        logger.info(
            "章节续写请求：novel_id=%s, chapter_id=%s, target_length=%s, pace=%s, tone=%s, plot_direction_hint=%s",
            request.novel_id,
            request.chapter_id,
            request.target_length,
            request.pace,
            request.tone,
            (request.plot_direction_hint or ""),
        )

        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 获取当前章节信息，确保章节属于该小说
        chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
        if not chapter or chapter.novel_id != request.novel_id:
            raise HTTPException(status_code=404, detail="章节不存在或不属于该小说")
        _validate_source_identity(request, novel, chapter)

        # 文风特征与上下文
        style_features: list[str] = []
        style_guide = ""
        style_sample_id = request.style_sample_id
        rag_style_context: list[str] = []

        # 优先使用用户上传的文风样本
        if style_sample_id is not None:
            sample = novel_crud.get_style_sample_by_id(db, style_sample_id)
            if not sample or sample.novel_id != request.novel_id:
                raise HTTPException(status_code=404, detail="文风样本不存在或不属于该小说")

            try:
                style_features = json.loads(sample.style_features) if sample.style_features else []
            except Exception:
                style_features = []

            # 根据文风强度构造指导
            if request.style_strength > 0:
                if style_features:
                    style_guide = "\n\n【文风指导】请尽量参考以下文风特征进行创作：\n" + "\n".join(
                        f"- {feat}" for feat in style_features
                    )

            # 将样本文本的一部分作为风格上下文
            rag_style_context.append(sample.sample_text[:300])

        # 如果没有文风样本但开启了RAG文风分析，则退回到基于当前内容的启发式分析
        elif request.use_rag_style and request.current_content:
            if len(request.current_content) > 100:
                sample_text = (
                    request.current_content[-500:]
                    if len(request.current_content) > 500
                    else request.current_content
                )

                # 统计句子长度和结构
                sentences = (
                    sample_text.replace('。', '。\n')
                    .replace('！', '！\n')
                    .replace('？', '？\n')
                    .split('\n')
                )
                sentences = [s.strip() for s in sentences if s.strip()]

                if sentences:
                    avg_length = sum(len(s) for s in sentences) / len(sentences)

                    if avg_length < 15:
                        style_features.append("使用简短有力的句式")
                    elif avg_length > 30:
                        style_features.append("使用细腻详尽的长句描写")
                    else:
                        style_features.append("使用长短句结合的叙事方式")

                # 检测描写风格
                if '，' in sample_text and sample_text.count('，') > len(sample_text) / 50:
                    style_features.append("善用逗号进行细节铺陈")

                if any(word in sample_text for word in ['只见', '但见', '忽见', '忽听', '忽闻']):
                    style_features.append("采用古典小说的叙事手法")

                if any(word in sample_text for word in ['心中', '心想', '暗道', '暗想']):
                    style_features.append("注重心理描写")

                if request.style_strength > 0.5 and style_features:
                    style_guide = "\n\n【文风指导】请严格保持以下文风特征：\n" + "\n".join(
                        f"- {feat}" for feat in style_features
                    )

        # 构造节奏指导
        pace_guide = {
            "slow": "采用舒缓的节奏，详细描写场景和心理活动，营造沉浸感。",
            "medium": "保持适中的叙事节奏，情节推进与描写平衡。",
            "fast": "采用快节奏叙事，简洁明快，快速推进情节。"
        }.get(request.pace, "")

        # 构造情感基调指导
        tone_guide = {
            "neutral": "",
            "tense": "营造紧张氛围，增强冲突感和悬念。",
            "relaxed": "保持轻松愉快的氛围，注重趣味性。",
            "sad": "渲染悲伤情绪，注重情感共鸣。",
            "joyful": "营造欢快氛围，传递积极向上的情绪。"
        }.get(request.tone, "")

        # 构造剧情走向提示
        plot_direction_hint = (
            request.plot_direction_hint.strip() if isinstance(request.plot_direction_hint, str) else ""
        )
        plot_hint_part = f"\n- 剧情走向：{plot_direction_hint}" if plot_direction_hint else ""

        # 构造完整的续写提示词
        worldview_context = compact_text(
            novel.worldview,
            MAX_WORLDVIEW_CONTEXT_CHARS,
            keep="head",
        ) or "无"
        current_context = compact_text(
            request.current_content,
            MAX_STORY_CONTEXT_CHARS,
            keep="tail",
        )
        prompt = f"""请根据以下内容继续创作约{request.target_length}字的小说段落。

【小说信息】
标题：{novel.title}
类型：{novel.genre or '未指定'}
世界观：{worldview_context}

【已有内容】
{current_context}

【创作要求】
- 目标字数：约{request.target_length}字
- 叙事节奏：{pace_guide}
- 情感基调：{tone_guide}
{style_guide}{plot_hint_part}

请自然地续写故事，保持情节连贯性和人物一致性。

续写："""
        prompt = compact_text(
            prompt,
            MAX_GENERATION_PROMPT_CHARS,
            keep="both",
        )

        novel_snapshot = SimpleNamespace(id=novel.id, rag_lifecycle_id=novel.rag_lifecycle_id)
        chapter_snapshot = SimpleNamespace(id=chapter.id, version=chapter.version, rag_lifecycle_id=chapter.rag_lifecycle_id)
        actor_id = current_user.id
        # 调用生成服务
        gen_request = GenerationRequest(
            novel_id=request.novel_id,
            prompt=prompt,
            chapter=chapter.chapter_number,
            current_day=request.current_day,
            target_length=request.target_length,
        )
        response = await agent_service.generate_content(
            gen_request, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id,
        )

        proposal = create_proposal(db, novel=novel_snapshot, actor_id=actor_id,
            chapter=chapter_snapshot, base_content=request.current_content, operation='append',
            content=response.final_content, context_manifest=response.context_manifest, execution=response.execution)
        db.commit()

        # 工作流追踪（用于前端可视化多Agent执行过程）
        workflow_trace = (
            response.workflow_trace.model_dump()
            if getattr(response, "workflow_trace", None) is not None
            else None
        )

        logger.info(
            f"章节续写成功：小说{request.novel_id}，章节{chapter.chapter_number}，生成{len(response.final_content)}字，节奏={request.pace}，基调={request.tone}"
        )

        return {
            "content": response.final_content,
            "proposal_id": proposal.id,
            "length": len(response.final_content),
            "style_features": style_features,
            "style_sample_id": style_sample_id,
            "rag_style_context": rag_style_context,
            "rag_story_context": response.worldview_context + response.character_context + response.story_bible_context,
            "context_manifest": response.context_manifest,
            "execution": response.execution,
            "agent_outputs": [output.model_dump() for output in response.agent_outputs],
            "consistency_checks": [
                check.model_dump() for check in response.consistency_checks
            ],
            "retry_count": response.retry_count,
            "final_consistency": response.final_consistency.model_dump(),
            "workflow_trace": workflow_trace,
            "settings": {
                "pace": request.pace,
                "tone": request.tone,
                "style_strength": request.style_strength
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"章节续写失败: {e}")
        raise HTTPException(status_code=500, detail=f"续写失败: {str(e)}")


async def _continue_chapter_stream_impl(
    request: ContinueRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """章节续写流式接口
    
    使用与 `/generation/continue` 相同的多Agent工作流，但通过SSE将结果按块推送给前端，
    以便工作台实现真正的流式展示效果。
    """
    try:
        logger.info(
            "章节续写流式请求：novel_id=%s, chapter_id=%s",
            request.novel_id,
            request.chapter_id,
        )

        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 获取当前章节信息
        chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
        if not chapter or chapter.novel_id != request.novel_id:
            raise HTTPException(status_code=404, detail="章节不存在或不属于该小说")
        _validate_source_identity(request, novel, chapter)

        # 文风特征与上下文
        style_features: list[str] = []
        style_guide = ""
        style_sample_id = request.style_sample_id
        rag_style_context: list[str] = []

        # 优先使用用户上传的文风样本
        if style_sample_id is not None:
            sample = novel_crud.get_style_sample_by_id(db, style_sample_id)
            if not sample or sample.novel_id != request.novel_id:
                raise HTTPException(status_code=404, detail="文风样本不存在或不属于该小说")

            try:
                style_features = json.loads(sample.style_features) if sample.style_features else []
            except Exception:
                style_features = []

            if request.style_strength > 0:
                if style_features:
                    style_guide = "\n\n【文风指导】请尽量参考以下文风特征进行创作：\n" + "\n".join(
                        f"- {feat}" for feat in style_features
                    )
            rag_style_context.append(sample.sample_text[:300])

        # 如果没有文风样本但开启了RAG文风分析
        elif request.use_rag_style and request.current_content:
            if len(request.current_content) > 100:
                sample_text = (
                    request.current_content[-500:]
                    if len(request.current_content) > 500
                    else request.current_content
                )
                # 简易文风分析
                sentences = [s.strip() for s in sample_text.replace('。', '。\n').split('\n') if s.strip()]
                if sentences:
                    avg_length = sum(len(s) for s in sentences) / len(sentences)
                    if avg_length < 15:
                        style_features.append("使用简短有力的句式")
                    elif avg_length > 30:
                        style_features.append("使用细腻详尽的长句描写")
                
                if request.style_strength > 0.5 and style_features:
                    style_guide = "\n\n【文风指导】请严格保持以下文风特征：\n" + "\n".join(
                        f"- {feat}" for feat in style_features
                    )

        # 构造节奏指导
        pace_guide = {
            "slow": "采用舒缓的节奏，详细描写场景和心理活动，营造沉浸感。",
            "medium": "保持适中的叙事节奏，情节推进与描写平衡。",
            "fast": "采用快节奏叙事，简洁明快，快速推进情节。"
        }.get(request.pace, "")

        # 构造情感基调指导
        tone_guide = {
            "neutral": "",
            "tense": "营造紧张氛围，增强冲突感和悬念。",
            "relaxed": "保持轻松愉快的氛围，注重趣味性。",
            "sad": "渲染悲伤情绪，注重情感共鸣。",
            "joyful": "营造欢快氛围，传递积极向上的情绪。"
        }.get(request.tone, "")

        # 构造剧情走向提示
        plot_direction_hint = (
            request.plot_direction_hint.strip() if isinstance(request.plot_direction_hint, str) else ""
        )
        plot_hint_part = f"\n- 剧情走向：{plot_direction_hint}" if plot_direction_hint else ""

        # 构造完整的续写提示词
        worldview_context = compact_text(
            novel.worldview,
            MAX_WORLDVIEW_CONTEXT_CHARS,
            keep="head",
        ) or "无"
        current_context = compact_text(
            request.current_content,
            MAX_STORY_CONTEXT_CHARS,
            keep="tail",
        )
        prompt = f"""请根据以下内容继续创作约{request.target_length}字的小说段落。

【小说信息】
标题：{novel.title}
类型：{novel.genre or '未指定'}
世界观：{worldview_context}

【已有内容】
{current_context}

【创作要求】
- 目标字数：约{request.target_length}字
- 叙事节奏：{pace_guide}
- 情感基调：{tone_guide}
{style_guide}{plot_hint_part}

请自然地续写故事，保持情节连贯性和人物一致性。

续写："""
        prompt = compact_text(
            prompt,
            MAX_GENERATION_PROMPT_CHARS,
            keep="both",
        )

        # 构造生成请求
        gen_request = GenerationRequest(
            novel_id=request.novel_id,
            prompt=prompt,
            chapter=chapter.chapter_number,
            current_day=request.current_day,
            target_length=request.target_length,
        )

        novel_snapshot = SimpleNamespace(id=novel.id, rag_lifecycle_id=novel.rag_lifecycle_id)
        chapter_snapshot = SimpleNamespace(id=chapter.id, version=chapter.version, rag_lifecycle_id=chapter.rag_lifecycle_id)
        generation_actor_id = novel.user_id
        generation_lifecycle_id = novel.rag_lifecycle_id

        async def event_generator():
            """SSE事件生成器"""
            try:
                async for event in agent_service.generate_content_stream(
                    gen_request, actor_id=generation_actor_id,
                    novel_lifecycle_id=generation_lifecycle_id,
                ):
                    if await http_request.is_disconnected():
                        logger.info(
                            "客户端已断开续写流：novel_id={}, chapter_id={}",
                            request.novel_id,
                            request.chapter_id,
                        )
                        break
                    if event["type"] == "final_response":
                        response = event["data"]
                        proposal = create_proposal(db, novel=novel_snapshot, actor_id=generation_actor_id,
                            chapter=chapter_snapshot, base_content=request.current_content, operation='append',
                            content=response.final_content, context_manifest=response.context_manifest, execution=response.execution)
                        db.commit()
                        
                        # 发送元数据
                        workflow_trace = (
                            response.workflow_trace.model_dump()
                            if getattr(response, "workflow_trace", None) is not None
                            else None
                        )
                        
                        metadata = {
                            "proposal_id": proposal.id,
                            "style_features": style_features,
                            "style_sample_id": style_sample_id,
                            "rag_style_context": rag_style_context,
                            "rag_story_context": response.worldview_context + response.character_context + response.story_bible_context,
                            "context_manifest": response.context_manifest,
                            "execution": response.execution,
                            "agent_outputs": [output.model_dump() for output in response.agent_outputs],
                            "consistency_checks": [
                                check.model_dump() for check in response.consistency_checks
                            ],
                            "retry_count": response.retry_count,
                            "final_consistency": response.final_consistency.model_dump(),
                            "workflow_trace": workflow_trace,
                            "settings": {
                                "pace": request.pace,
                                "tone": request.tone,
                                "style_strength": request.style_strength
                            }
                        }
                        yield f"data: {json.dumps({'type': 'metadata', 'data': metadata}, default=str)}\n\n"
                        
                        # 发送正文块
                        full_content = response.final_content
                        chunk_size = max(1, len(full_content))  # 完整候选一次交付，不伪装提供方token流
                        for i in range(0, len(full_content), chunk_size):
                            if await http_request.is_disconnected():
                                return
                            chunk = full_content[i:i+chunk_size]
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

                        
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    else:
                        # 转发Agent事件
                        event_data = event.get("data")
                        safe_event = {
                            "type": event["type"],
                            "agent": event.get("agent"),
                            "status": event.get("status"),
                            "data": event_data
                        }
                        yield f"data: {json.dumps(safe_event, ensure_ascii=False)}\n\n"

            except asyncio.CancelledError:
                logger.info(
                    "续写流任务已取消：novel_id={}, chapter_id={}",
                    request.novel_id,
                    request.chapter_id,
                )
                raise
            except Exception as e:
                logger.error(f"流式生成过程中发生错误: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        # 直接透传业务错误，前端会在进入流式处理前通过 res.ok 检查
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"章节续写流式接口失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"续写失败: {str(e)}")


@router.post("/outline")
@durable_route('outline')
async def generate_outline(request: OutlineRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """严格大纲结构独立生成，不经过环境/人物/正文三阶段。"""
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(404, '小说不存在或无权访问')
    try:
        result, pack, execution = await _run_structured_task(db, novel, mode='outline',
            instruction=request.theme, options=TaskOptions(target_chapters=request.target_chapters))
        return {'outline': result.text, 'chapters': request.target_chapters, 'result': result.result,
                'context_manifest': pack.manifest, 'execution': execution}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, '未能生成符合要求的完整大纲，请重试') from exc


@router.post("/character")
@durable_route('character')
async def generate_character(request: CharacterRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """角色设计独立返回严格字段，不被正文续写指令改写为段落。"""
    novel = novel_crud.get_novel_by_id(db, request.novel_id)
    if not novel or novel.user_id != current_user.id:
        raise HTTPException(404, '小说不存在或无权访问')
    try:
        result, pack, execution = await _run_structured_task(db, novel, mode='character',
            instruction=request.character_description, options=TaskOptions(character_type=request.character_type))
        return {'character': result.text, 'type': request.character_type, 'result': result.result,
                'context_manifest': pack.manifest, 'execution': execution}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, '未能生成符合要求的完整角色设定，请重试') from exc


@router.get("/test")
async def test_generation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    测试接口：生成示例内容

    用于快速测试系统是否正常工作
    """
    try:
        if not settings.DEBUG:
            raise HTTPException(status_code=404, detail="接口不存在")
        novel = novel_crud.get_novel_by_id(db, 1)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")
        request = GenerationRequest(
            novel_id=1,
            prompt="主角在魔法塔顶与导师决裂",
            chapter=1,
            target_length=500
        )
        response = await agent_service.generate_content(
            request, actor_id=novel.user_id, novel_lifecycle_id=novel.rag_lifecycle_id,
        )
        return {
            "message": "测试成功",
            "context_manifest": response.context_manifest,
            "final_content": response.final_content,
            "length": len(response.final_content)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"测试失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"测试失败: {str(e)}"
        )


@router.post('/continue-stream')
async def continue_chapter_stream(request: ContinueRequest, http_request: Request,
                                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bind, actor_id, novel_id = db.get_bind(), current_user.id, request.novel_id
    job_id = await asyncio.to_thread(submit_legacy_job, bind, novel_id=novel_id,
        actor_id=actor_id, kind='continue_stream', payload=request.model_dump(mode='json'))
    dispatch_job(bind, job_id)

    async def events():
        from sqlalchemy.orm import sessionmaker
        sessions = sessionmaker(bind=bind)
        position = 0
        yield 'data: ' + json.dumps({'type': 'job', 'data': {'job_id': job_id}}) + '\n\n'
        while True:
            if await http_request.is_disconnected():
                return
            def read_events():
                with sessions() as read_db:
                    current = owned_job(read_db, job_id, novel_id, actor_id)
                    return (current.result or {}).get('events', []), current.status, current.error
            available, state, error = await asyncio.to_thread(read_events)
            for event in available[position:]:
                yield 'data: ' + json.dumps(event, ensure_ascii=False, default=str) + '\n\n'
            position = len(available)
            if state in {'failed', 'cancelled'}:
                yield 'data: ' + json.dumps({'type': 'error', 'message': error or '生成已中断'}, ensure_ascii=False) + '\n\n'
                return
            if state == 'completed':
                return
            await asyncio.sleep(0.1)
    return StreamingResponse(events(), media_type='text/event-stream')


class GenerationJobCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    novel_id: int = Field(gt=0)
    expected_novel_lifecycle_id: str = Field(min_length=32, max_length=32)
    kind: Literal['chat', 'generate', 'continue', 'rewrite', 'auto_chapter', 'outline', 'character', 'init', 'plot_options']
    payload: dict


class GenerationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    request_id: str
    novel_id: int
    novel_lifecycle_id: str
    chapter_id: int | None = None
    chapter_lifecycle_id: str | None = None
    message: str | None = None
    mode: str | None = None
    chapter_title: str | None = None
    kind: str
    status: str
    result: dict | None = None
    execution: dict | None = None
    error: str | None = None
    error_code: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


def _job_response(job):
    response = GenerationJobResponse.model_validate(job)
    response.chapter_id = (job.source_scope or {}).get('chapter_id')
    response.chapter_lifecycle_id = (job.source_scope or {}).get('chapter_lifecycle_id')
    response.chapter_title = (job.source_scope or {}).get('chapter_title')
    if job.kind == 'chat':
        response.message = job.payload.get('message')
        response.mode = job.payload.get('mode')
    return response


def _job_payload(kind, payload, novel_id, request_id):
    from app.api.routes.writing_chat import TurnCreate
    schemas = {'init': InitNovelRequest, 'plot_options': PlotOptionsRequest, 'chat': TurnCreate, 'generate': GenerationRequest, 'continue': ContinueRequest,
               'rewrite': RewriteRequest, 'auto_chapter': AutoChapterRequest,
               'outline': OutlineRequest, 'character': CharacterRequest}
    try:
        parsed = schemas[kind].model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, '创作任务参数不符合当前工具要求') from exc
    if kind == 'chat':
        if str(parsed.request_id) != str(request_id):
            raise HTTPException(422, '对话与执行任务必须使用同一个请求标识')
    elif parsed.novel_id != novel_id:
        raise HTTPException(422, '任务与请求中的作品标识不一致')
    return parsed.model_dump(mode='json')


@router.post('/jobs', status_code=202, response_model=GenerationJobResponse)
def create_generation_job(data: GenerationJobCreate, db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    payload = _job_payload(data.kind, data.payload, data.novel_id, data.request_id)
    reconcile_jobs(db)
    job = submit_job(db, novel_id=data.novel_id, actor_id=user.id,
        lifecycle=data.expected_novel_lifecycle_id, request_id=str(data.request_id), kind=data.kind, payload=payload)
    response = _job_response(job)
    dispatch_job(db.get_bind(), job.id)
    return response


@router.get('/jobs', response_model=list[GenerationJobResponse])
def list_generation_jobs(novel_id: int = Query(gt=0), kind: str | None = None,
                         chapter_id: int | None = Query(None, gt=0),
                         limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    novel = novel_crud.get_novel_by_id(db, novel_id)
    if novel is None or novel.user_id != user.id:
        raise HTTPException(404, '小说不存在或无权访问')
    lifecycle = novel.rag_lifecycle_id
    reconcile_jobs(db)
    query = db.query(WritingGenerationJob).filter_by(novel_id=novel_id, actor_id=user.id, novel_lifecycle_id=lifecycle)
    if kind is not None:
        query = query.filter_by(kind=kind)
    if chapter_id is not None:
        query = query.filter(WritingGenerationJob.source_scope['chapter_id'].as_integer() == chapter_id)
    return [_job_response(job) for job in query.order_by(WritingGenerationJob.created_at.desc(), WritingGenerationJob.id.desc()).limit(limit)]


@router.get('/jobs/{job_id}', response_model=GenerationJobResponse)
def get_generation_job(job_id: UUID, novel_id: int = Query(gt=0), db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    job = owned_job(db, job_id, novel_id, user.id)
    reconcile_jobs(db)
    db.refresh(job)
    return _job_response(job)


@router.post('/jobs/{job_id}/stop', response_model=GenerationJobResponse)
def stop_generation_job(job_id: UUID, novel_id: int = Query(gt=0), db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    return _job_response(stop_job(db, owned_job(db, job_id, novel_id, user.id)))


class GenerationJobRetry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


@router.post('/jobs/{job_id}/retry', status_code=202, response_model=GenerationJobResponse)
def retry_generation_job(job_id: UUID, data: GenerationJobRetry, novel_id: int = Query(gt=0),
                               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    original = owned_job(db, job_id, novel_id, user.id)
    reconcile_jobs(db)
    db.refresh(original)
    if original.status not in {'failed', 'cancelled'}:
        raise HTTPException(409, '只有失败或停止的执行可以重试')
    payload = dict(original.payload)
    if original.kind == 'chat':
        payload['request_id'] = str(data.request_id)
    job = submit_job(db, novel_id=novel_id, actor_id=user.id, lifecycle=original.novel_lifecycle_id,
        request_id=str(data.request_id), kind=original.kind, payload=payload, source_scope=original.source_scope)
    response = _job_response(job)
    dispatch_job(db.get_bind(), job.id)
    return response


class _DetachedRequest:
    async def is_disconnected(self):
        return False


async def _stream_job_handler(payload, novel_id, actor, db):
    return await _continue_chapter_stream_impl(request=ContinueRequest.model_validate(payload),
        http_request=_DetachedRequest(), current_user=actor, db=db)


register_handler('continue_stream', _stream_job_handler)


def _register_generation_handlers():
    for kind, schema, handler in [
        ('init', InitNovelRequest, init_novel), ('plot_options', PlotOptionsRequest, generate_plot_options),
        ('generate', GenerationRequest, generate_content), ('continue', ContinueRequest, continue_chapter),
        ('rewrite', RewriteRequest, rewrite_text), ('auto_chapter', AutoChapterRequest, auto_create_chapter),
        ('outline', OutlineRequest, generate_outline), ('character', CharacterRequest, generate_character),
    ]:
        async def execute(payload, novel_id, actor, db, schema=schema, handler=handler, kind=kind):
            kwargs = {'request': schema.model_validate(payload), 'current_user': actor, 'db': db}
            if kind == 'auto_chapter':
                kwargs['background_tasks'] = BackgroundTasks()
            result = await handler(**kwargs)
            if kind == 'auto_chapter':
                return ProposalResponse.model_validate(result).model_dump(mode='json')
            return result
        register_handler(kind, execute)


_register_generation_handlers()
