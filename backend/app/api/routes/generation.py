"""
内容生成路由
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request, status
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
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from app.core.config import settings
import json
import asyncio
from app.services.context_budget import (
    MAX_CURRENT_CONTENT_CHARS,
    MAX_GENERATION_PROMPT_CHARS,
    MAX_PLOT_HINT_CHARS,
    MAX_STORY_CONTEXT_CHARS,
    MAX_WORLDVIEW_CONTEXT_CHARS,
    compact_text,
    ensure_generation_prompt_budget,
)

router = APIRouter()


async def _index_auto_chapter_projection(**kwargs) -> None:
    """后台刷新自动生成章节的RAG投影，并记录真实执行结果。"""
    indexed = await rag_service.index_content(**kwargs)
    if indexed:
        logger.info(
            "自动章节RAG后台索引完成：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )
    elif not settings.EMBEDDING_ENABLED:
        logger.info(
            "自动章节RAG后台索引已按配置跳过：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )
    else:
        logger.warning(
            "自动章节RAG后台索引失败：novel_id={}, chapter={}",
            kwargs["novel_id"],
            kwargs["chapter"],
        )


# 初始化设定使用的LLM
init_llm = ChatOpenAI(
    model=settings.OPENAI_MODEL_COMPLEX,
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_API_BASE,
    temperature=0.8,
    max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
    timeout=settings.LLM_TIMEOUT_SECONDS,
    max_retries=settings.LLM_MAX_RETRIES,
)


class ContinueRequest(BaseModel):
    """章节续写请求"""
    novel_id: int = Field(..., gt=0)
    chapter_id: int = Field(..., gt=0)
    current_content: str = Field(..., max_length=MAX_CURRENT_CONTENT_CHARS)
    target_length: int = Field(500, ge=100, le=3000)
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
    target_chapters: int = Field(10, ge=1, le=80)


class CharacterRequest(BaseModel):
    """角色生成请求"""
    novel_id: int = Field(..., gt=0)
    character_type: str = Field(..., min_length=1, max_length=20)
    character_description: str = Field(..., min_length=1, max_length=1000)


@router.post("/init", response_model=InitNovelResponse)
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
        result = await chain.ainvoke(
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

        raw = result.content.strip()

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
        response = await agent_service.generate_content(request)
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
        response = await chain.ainvoke(
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

        raw = response.content.strip()

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


@router.post("/auto-chapter", response_model=ChapterResponse)
async def auto_create_chapter(
    request: AutoChapterRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI自动生成并创建新章节

    根据小说设定和参考章节，自动生成下一章的章节号、标题和正文，并写入数据库。
    """
    try:
        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 确定参考章节
        base_chapter = None
        if request.base_chapter_id is not None:
            base_chapter = novel_crud.get_chapter_by_id(db, request.base_chapter_id)
            if not base_chapter or base_chapter.novel_id != request.novel_id:
                raise HTTPException(status_code=404, detail="参考章节不存在")
        else:
            # 只读取最后一章，避免为选取参考内容加载整部小说正文。
            base_chapter = novel_crud.get_latest_chapter(db, request.novel_id)

        # 该编号仅用于提示模型；真正的章节号在写入时由服务端重新分配。
        next_chapter_number = novel_crud.get_max_chapter_number(db, request.novel_id) + 1
        if base_chapter:
            base_content = base_chapter.content or ""
        else:
            base_content = ""

        # 构造提示词
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """你是一名专业的长篇小说写作助手，负责为作者自动生成新章节。

你的任务：
1. 根据小说设定和参考内容，设计下一章的章节标题和完整正文初稿。
2. 章节标题要简洁、有记忆点，并且符合该章的核心冲突或事件。
3. 正文需要在指定字数范围内（可略有浮动），保持与前文一致的人设和世界观。
4. 输出必须使用JSON格式：{{"title": "章节标题", "content": "章节正文"}}，不要添加其他内容。
""",
            ),
            (
                "user",
                """小说标题：{title}
小说类型：{genre}
世界观（节选）：{worldview}
故事简介：{description}

参考章节号：{base_chapter_number}
参考章节标题：{base_chapter_title}
参考章节内容（节选）：{base_excerpt}

本章剧情重点：{theme}
目标章节号：{target_chapter_number}
目标字数：约{target_length}字
""",
            ),
        ])

        base_excerpt = compact_text(base_content, 800, keep="tail")
        worldview_excerpt = compact_text(
            novel.worldview,
            MAX_WORLDVIEW_CONTEXT_CHARS,
            keep="head",
        ) or "未设定"
        description_excerpt = compact_text(
            novel.description,
            MAX_STORY_CONTEXT_CHARS,
            keep="head",
        ) or "暂无简介"
        theme_excerpt = compact_text(
            request.theme,
            MAX_PLOT_HINT_CHARS,
            keep="head",
        ) or "无特别说明"

        chain = prompt | init_llm
        response = await chain.ainvoke(
            {
                "title": novel.title,
                "genre": novel.genre or "未指定",
                "worldview": worldview_excerpt,
                "description": description_excerpt,
                "base_chapter_number": base_chapter.chapter_number if base_chapter else "无",
                "base_chapter_title": base_chapter.title if base_chapter else "无",
                "base_excerpt": base_excerpt or "暂无内容",
                "theme": theme_excerpt,
                "target_chapter_number": next_chapter_number,
                "target_length": request.target_length,
            }
        )

        raw = response.content.strip()
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            json_str = raw[start:end] if start != -1 and end != 0 else raw
            data = json.loads(json_str)
            title = str(data.get("title") or "").strip() or None
            content = str(data.get("content") or "")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"解析自动章节JSON失败，将原始内容作为正文返回: {e}")
            title = None
            content = raw

        # 模型若只回显预测编号，让数据库写入后的真实编号决定默认标题。
        if title == f"第{next_chapter_number}章":
            title = None
        chapter_create = ChapterNextCreate(
            title=title,
            content=content,
        )

        # 在模型调用结束后重新计算并分配章节号，数据库唯一约束负责并发兜底。
        try:
            db_chapter = novel_crud.create_next_chapter(
                db,
                request.novel_id,
                chapter_create,
            )
        except novel_crud.ChapterNumberConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        # 向量索引是可重建投影，不阻塞章节创建响应。
        projection_token = rag_service.prepare_chapter_projection(
            request.novel_id,
            db_chapter.id,
            db=db,
        )
        background_tasks.add_task(
            _index_auto_chapter_projection,
            novel_id=request.novel_id,
            chapter=db_chapter.chapter_number,
            content=db_chapter.content,
            metadata={
                "source": "chapter",
                "chapter_id": db_chapter.id,
                "version": db_chapter.version,
                **projection_token,
            },
        )

        return ChapterResponse.model_validate(db_chapter)

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"AI自动生成章节失败: {e}")
        raise HTTPException(status_code=500, detail=f"自动生成章节失败: {str(e)}")


@router.post("/rewrite", response_model=RewriteResponse)
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

        if request.chapter_id is not None:
            chapter = novel_crud.get_chapter_by_id(db, request.chapter_id)
            if not chapter or chapter.novel_id != request.novel_id:
                raise HTTPException(status_code=404, detail="章节不存在")

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
        result = await chain.ainvoke({"user_request": user_prompt})
        rewritten = result.content.strip()

        if not rewritten:
            raise HTTPException(status_code=500, detail="改写失败，模型返回为空")

        return RewriteResponse(rewritten_text=rewritten)

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"局部改写失败: {e}")
        raise HTTPException(status_code=500, detail=f"改写失败: {str(e)}")


@router.post("/continue")
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

        # 调用生成服务
        gen_request = GenerationRequest(
            novel_id=request.novel_id,
            prompt=prompt,
            chapter=chapter.chapter_number,
            current_day=1,
            target_length=request.target_length,
        )
        response = await agent_service.generate_content(gen_request)

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
            "length": len(response.final_content),
            "style_features": style_features,
            "style_sample_id": style_sample_id,
            "rag_style_context": rag_style_context,
            "rag_story_context": response.worldview_context + response.character_context + response.story_bible_context,
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


@router.post("/continue-stream")
async def continue_chapter_stream(
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
            current_day=1,
            target_length=request.target_length,
        )

        async def event_generator():
            """SSE事件生成器"""
            try:
                async for event in agent_service.generate_content_stream(gen_request):
                    if await http_request.is_disconnected():
                        logger.info(
                            "客户端已断开续写流：novel_id={}, chapter_id={}",
                            request.novel_id,
                            request.chapter_id,
                        )
                        break
                    if event["type"] == "final_response":
                        response = event["data"]
                        
                        # 发送元数据
                        workflow_trace = (
                            response.workflow_trace.model_dump()
                            if getattr(response, "workflow_trace", None) is not None
                            else None
                        )
                        
                        metadata = {
                            "style_features": style_features,
                            "style_sample_id": style_sample_id,
                            "rag_style_context": rag_style_context,
                            "rag_story_context": response.worldview_context + response.character_context + response.story_bible_context,
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
                        chunk_size = 5  # 每次发送5个字符，模拟打字
                        for i in range(0, len(full_content), chunk_size):
                            if await http_request.is_disconnected():
                                return
                            chunk = full_content[i:i+chunk_size]
                            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                            await asyncio.sleep(0.01)
                        
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
async def generate_outline(
    request: OutlineRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    生成小说大纲

    Args:
        request: 大纲生成请求（包含主题和章节数）
        current_user: 当前用户
        db: 数据库会话

    Returns:
        生成的大纲（章节列表）
    """
    try:
        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 构造大纲生成提示词
        worldview_context = compact_text(
            novel.worldview,
            MAX_WORLDVIEW_CONTEXT_CHARS,
            keep="head",
        ) or "未设定"
        prompt = f"""请为以下小说生成{request.target_chapters}章的详细大纲：

小说标题：{novel.title}
小说类型：{novel.genre or '未指定'}
故事主题：{request.theme}
世界观：{worldview_context}

请按照以下格式生成大纲：
第X章 章节标题
- 主要情节点1
- 主要情节点2
- 主要情节点3
"""
        prompt = compact_text(prompt, MAX_GENERATION_PROMPT_CHARS, keep="both")

        # 调用生成服务
        gen_request = GenerationRequest(
            novel_id=request.novel_id,
            prompt=prompt,
            chapter=1,
            current_day=1,
            target_length=request.target_chapters * 100
        )
        response = await agent_service.generate_content(gen_request)

        logger.info(f"大纲生成成功：小说{request.novel_id}，{request.target_chapters}章")

        return {
            "outline": response.final_content,
            "chapters": request.target_chapters
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"大纲生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@router.post("/character")
async def generate_character(
    request: CharacterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    生成角色设定

    Args:
        request: 角色生成请求
        current_user: 当前用户
        db: 数据库会话

    Returns:
        生成的角色设定
    """
    try:
        # 验证小说所有权
        novel = novel_crud.get_novel_by_id(db, request.novel_id)
        if not novel or novel.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="小说不存在或无权访问")

        # 构造角色生成提示词
        worldview_context = compact_text(
            novel.worldview,
            MAX_WORLDVIEW_CONTEXT_CHARS,
            keep="head",
        ) or "未设定"
        prompt = f"""请为以下小说生成一个{request.character_type}角色的详细设定：

小说标题：{novel.title}
小说类型：{novel.genre or '未指定'}
世界观：{worldview_context}

角色类型：{request.character_type}
角色描述：{request.character_description}

请生成以下内容：
1. 姓名
2. 年龄/外貌
3. 性格特点
4. 背景故事
5. 能力/特长
6. 动机/目标
7. 人物关系
"""
        prompt = compact_text(prompt, MAX_GENERATION_PROMPT_CHARS, keep="both")

        # 调用生成服务
        gen_request = GenerationRequest(
            novel_id=request.novel_id,
            prompt=prompt,
            chapter=1,
            current_day=1,
            target_length=500
        )
        response = await agent_service.generate_content(gen_request)

        logger.info(f"角色生成成功：小说{request.novel_id}，{request.character_type}")

        return {
            "character": response.final_content,
            "type": request.character_type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"角色生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


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
            current_day=1,
            target_length=500
        )
        response = await agent_service.generate_content(request)
        return {
            "message": "测试成功",
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
