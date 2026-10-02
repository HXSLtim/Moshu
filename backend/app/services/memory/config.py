"""简介配方身份：配置变化不能冒用旧提取结果。"""
import hashlib
import json

from app.core.config import settings
from app.services.context.budget import MAX_DIGEST_SOURCE_CHARS, MAX_DIGEST_CHAPTER_CHARS, MAX_DIGEST_SPAN_CHARS


def digest_recipe_version() -> str:
    """只纳入非敏感的模型/预算和显式 Prompt/Schema 版本。"""
    recipe = {
        "schema_prompt": "chapter-digest-v2-spans-segments",
        "model": settings.OPENAI_MODEL_SIMPLE,
        "max_tokens": settings.LLM_MAX_OUTPUT_TOKENS,
        "source_chars": MAX_DIGEST_SOURCE_CHARS,
        "chapter_chars": MAX_DIGEST_CHAPTER_CHARS,
        "span_chars": MAX_DIGEST_SPAN_CHARS,
        "temperature": 0.2,
        "reasoning_effort": settings.LLM_REASONING_EFFORT,
        "json_schema_enabled": settings.LLM_JSON_SCHEMA_ENABLED,
    }
    return "chapter-digest-v2-" + hashlib.sha256(
        json.dumps(recipe, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
