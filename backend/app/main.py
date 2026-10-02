"""
FastAPI主入口文件
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import projection_jobs, story_memory
from app.api.routes import generation, health, auth, novels, style, research, rag, consistency, characters, mcp, review, story_bible, writing_chat, chapter_memory
from loguru import logger
import asyncio
from contextlib import suppress
import sys

# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.LOG_LEVEL
)

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="作者主导的长篇小说创作平台：常驻创作 Agent、固定生成工作流与可编排的复合任务",
    debug=settings.DEBUG
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 注册路由
app.include_router(story_memory.router, prefix="/api", tags=["剧情结构与核心状态"])
app.include_router(projection_jobs.router, prefix="/api", tags=["投影任务"])
app.include_router(health.router, prefix="/api", tags=["健康检查"])
app.include_router(auth.router, prefix="/api/auth", tags=["用户认证"])
app.include_router(novels.router, prefix="/api/novels", tags=["小说管理"])
app.include_router(characters.router, prefix="/api/characters", tags=["角色管理"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["统一MCP控制"])
app.include_router(generation.router, prefix="/api/generation", tags=["内容生成"])
app.include_router(style.router, prefix="/api/style", tags=["文风样本"])
app.include_router(research.router, prefix="/api/research", tags=["资料检索"])
app.include_router(rag.router, prefix="/api/rag", tags=["RAG调试"])
app.include_router(consistency.router, prefix="/api/consistency", tags=["一致性检查"])
app.include_router(review.router, prefix="/api/review", tags=["章节审核"])
app.include_router(writing_chat.router, prefix="/api/writing-chat", tags=["创作对话"])
app.include_router(story_bible.router, prefix="/api/story-bible", tags=["Story Bible"])
app.include_router(chapter_memory.router, prefix="/api", tags=["原文历史与章节简介"])


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    logger.info(f"📝 文档地址: http://localhost:8000/docs")
    logger.info(f"🔧 调试模式: {settings.DEBUG}")
    logger.info(f"🤖 LLM配置: base={settings.OPENAI_API_BASE}, complex={settings.OPENAI_MODEL_COMPLEX}, simple={settings.OPENAI_MODEL_SIMPLE}")
    logger.info(f"📋 已注册路由: 健康检查, 用户认证, 小说管理, 角色管理, Story Bible, 统一MCP控制, 内容生成, 文风样本, 资料检索, RAG调试, 一致性检查, 章节审核")
    app.state.writing_recovery_task = None
    if settings.WRITING_JOB_RECOVERY_ENABLED:
        from sqlalchemy import inspect
        from app.db.base import engine
        from app.services.conversation.jobs import run_recovery
        if "writing_generation_jobs" not in await asyncio.to_thread(lambda: inspect(engine).get_table_names()):
            raise RuntimeError("创作任务表尚未升级，请先备份并执行 python init_db.py")
        app.state.writing_recovery_stop = asyncio.Event()
        app.state.writing_recovery_task = asyncio.create_task(run_recovery(app.state.writing_recovery_stop))
    app.state.projection_task = None
    if settings.PROJECTION_WORKER_ENABLED:
        from sqlalchemy import inspect
        from app.db.base import engine
        from app.services.memory.projection import ProjectionWorker
        if "projection_jobs" not in inspect(engine).get_table_names():
            raise RuntimeError("投影任务表尚未升级，请先备份并执行 python init_db.py")
        app.state.projection_stop = asyncio.Event()
        app.state.projection_task = asyncio.create_task(ProjectionWorker().run_forever(app.state.projection_stop))
    app.state.memory_task = None
    if settings.MEMORY_WORKER_ENABLED:
        from sqlalchemy import inspect
        from app.db.base import engine
        from app.services.memory.worker import MemoryWorker
        required = {"chapter_revisions", "derived_jobs", "chapter_digests"}
        if not required.issubset(inspect(engine).get_table_names()):
            raise RuntimeError("章节记忆表尚未升级，请先备份数据库并执行 python init_db.py")
        app.state.memory_stop = asyncio.Event()
        app.state.memory_task = asyncio.create_task(MemoryWorker().run_forever(app.state.memory_stop))
        logger.info("章节简介后台提取已启用")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    from app.services.conversation.jobs import shutdown_writing_jobs
    await shutdown_writing_jobs()
    recovery = getattr(app.state, "writing_recovery_task", None)
    if recovery is not None:
        app.state.writing_recovery_stop.set()
        recovery.cancel()
        with suppress(asyncio.CancelledError):
            await recovery
    projection_task = getattr(app.state, "projection_task", None)
    if projection_task is not None:
        app.state.projection_stop.set()
        projection_task.cancel()
        with suppress(asyncio.CancelledError):
            await projection_task
    task = getattr(app.state, "memory_task", None)
    if task is not None:
        app.state.memory_stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    logger.info(f"👋 {settings.APP_NAME} 正在关闭...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
