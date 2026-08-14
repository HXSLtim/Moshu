"""
FastAPI主入口文件
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import generation, health, auth, novels, style, research, rag, consistency, characters, mcp, review, story_bible
from loguru import logger
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
    description="基于多Agent协作的智能小说创作平台",
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
app.include_router(story_bible.router, prefix="/api/story-bible", tags=["Story Bible"])


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    logger.info(f"📝 文档地址: http://localhost:8000/docs")
    logger.info(f"🔧 调试模式: {settings.DEBUG}")
    logger.info(f"🤖 LLM配置: base={settings.OPENAI_API_BASE}, complex={settings.OPENAI_MODEL_COMPLEX}, simple={settings.OPENAI_MODEL_SIMPLE}")
    logger.info(f"📋 已注册路由: 健康检查, 用户认证, 小说管理, 角色管理, Story Bible, 统一MCP控制, 内容生成, 文风样本, 资料检索, RAG调试, 一致性检查, 章节审核")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    logger.info(f"👋 {settings.APP_NAME} 正在关闭...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
