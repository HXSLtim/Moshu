"""候选只读响应契约，供对话与独立生成入口共同使用。"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    novel_id: int
    novel_lifecycle_id: str
    chapter_id: int | None
    chapter_lifecycle_id: str | None
    base_version: int
    base_content_hash: str
    operation: str
    target_chapter_number: int | None = None
    selection_start: int | None = None
    selection_end: int | None = None
    title: str | None
    content: str
    status: str
    context_manifest: dict | None
    execution: dict | None
    adopted_chapter_id: int | None
    adopted_version: int | None
    created_at: datetime


