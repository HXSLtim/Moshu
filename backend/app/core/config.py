"""
应用配置模块
使用Pydantic Settings管理环境变量
"""
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic import Field
from pydantic_settings import BaseSettings


BACKEND_DIR = Path(__file__).resolve().parents[2]
INSECURE_SECRET_KEYS = {
    "change_this_in_production",
    "your_secret_key_here_change_in_production",
}


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "AI小说创作系统"
    APP_VERSION: str = "0.1.0"
    # 双轨灰度开关(P4)：langgraph=旧链(默认零风险)/core=新核心链
    NAI_AGENT_RUNTIME: str = "langgraph"
    DEBUG: bool = True
    SECRET_KEY: str

    # OpenAI配置
    OPENAI_API_KEY: str = "lm-studio"
    OPENAI_API_BASE: str = "http://127.0.0.1:1234/v1"
    OPENAI_MODEL_COMPLEX: str = "google/gemma-4-26b-a4b-qat"
    OPENAI_MODEL_SIMPLE: str = "google/gemma-4-26b-a4b-qat"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_MAX_RETRIES: int = 2
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    LLM_REASONING_EFFORT: str | None = None
    LLM_JSON_SCHEMA_ENABLED: bool = False
    REVIEW_MAX_CONCURRENCY: int = 2

    # 保存只写持久任务；显式开启后才执行简介模型请求。
    MEMORY_WORKER_ENABLED: bool = False
    MEMORY_POLL_SECONDS: float = Field(2.0, gt=0)
    MEMORY_LEASE_SECONDS: float = Field(420.0, gt=0)
    MEMORY_MAX_ATTEMPTS: int = Field(3, ge=1, le=10)

    PROJECTION_WORKER_ENABLED: bool = True
    PROJECTION_POLL_SECONDS: float = Field(2.0, gt=0)
    PROJECTION_LEASE_SECONDS: float = Field(180.0, gt=0)
    PROJECTION_OPERATION_SECONDS: float = Field(120.0, gt=0)
    WRITING_JOB_RECOVERY_ENABLED: bool = True

    # PostgreSQL配置
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "novel_db"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres_password"

    # 当前稳定基线使用SQLite；部署PostgreSQL时只需覆盖此项。
    DATABASE_URL: str = f"sqlite:///{BACKEND_DIR / 'novel.db'}"

    # Chroma向量数据库配置（本地文件存储）
    CHROMA_DB_PATH: str = str(BACKEND_DIR / "chroma_db")
    CHROMA_COLLECTION_NAME: str = "novel_embeddings"

    # LM Studio提供OpenAI兼容的Embedding接口。
    EMBEDDING_ENABLED: bool = True
    EMBEDDING_API_BASE: str = "http://127.0.0.1:1234/v1"
    EMBEDDING_API_KEY: str = "lm-studio"
    EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v1.5"
    EMBEDDING_TIMEOUT_SECONDS: float = 60.0

    # Redis配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # Neo4j配置
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4j_password"
    NEO4J_ENABLED: bool = False

    # CORS配置
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://192.168.31.101:3000,http://192.168.31.101:8080,http://localhost:21490,http://127.0.0.1:21490"

    # 日志配置
    LOG_LEVEL: str = "INFO"

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        """拒绝仓库已知占位值，避免未配置环境直接形成 JWT 认证绕过。"""

        normalized = value.strip()
        if len(normalized) < 32 or normalized in INSECURE_SECRET_KEYS:
            raise ValueError("SECRET_KEY 必须是至少 32 个字符的随机值，且不能使用示例占位值")
        return normalized

    @property
    def database_url(self) -> str:
        """返回当前选定的数据库连接地址。"""
        return self.DATABASE_URL

    @property
    def allowed_origins_list(self) -> List[str]:
        """解析CORS允许的源"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    @property
    def redis_url(self) -> str:
        """生成Redis连接URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    class Config:
        """Pydantic配置"""
        env_file = (
            str(BACKEND_DIR.parent / ".env"),
            str(BACKEND_DIR / ".env"),
        )
        case_sensitive = True


# 创建全局配置实例
settings = Settings()
