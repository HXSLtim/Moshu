"""Story Bible 写入/读取 Schema。

写入请求统一继承 StrictWriteModel(拒绝未声明字段),所有自由文本
字段都带显式长度预算,防止 AI 链路与手动录入制造无界上下文。
"""

import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.schemas import StrictWriteModel

# 事实值允许略长于普通短文本:位置/状态描述常带一句语境。
MAX_FACT_VALUE_CHARS = 2_000
MAX_FACT_DESCRIPTION_CHARS = 4_000
MAX_EVENT_DESCRIPTION_CHARS = 8_000
MAX_FORESHADOWING_CHARS = 4_000
MAX_INVOLVED_CHARACTERS = 50


class FactCreate(StrictWriteModel):
    """创建故事事实:状态固定从 active 开始。"""

    novel_id: int = Field(..., gt=0, description="所属小说ID")
    subject: str = Field(..., min_length=1, max_length=100, description="主体(角色/地点/组织名)")
    attribute: str = Field(..., min_length=1, max_length=100, description="属性(如身份、位置、持有物)")
    value: str = Field(..., min_length=1, max_length=MAX_FACT_VALUE_CHARS, description="事实值")
    description: Optional[str] = Field(None, max_length=MAX_FACT_DESCRIPTION_CHARS, description="补充说明")
    chapter_established: Optional[int] = Field(None, gt=0, description="确立该事实的章节号")


class FactUpdate(StrictWriteModel):
    """更新事实:支持状态流转 active/retired。"""

    value: Optional[str] = Field(None, min_length=1, max_length=MAX_FACT_VALUE_CHARS)
    description: Optional[str] = Field(None, max_length=MAX_FACT_DESCRIPTION_CHARS)
    chapter_established: Optional[int] = Field(None, gt=0)
    status: Optional[str] = Field(None, pattern="^(active|retired)$", description="active 或 retired")
    retired_chapter: Optional[int] = Field(None, gt=0, description="失效章节号")

    @model_validator(mode="after")
    def validate_update_fields(self):
        """至少提供一个业务字段,避免空更新被误认为成功。"""
        fields = {"value", "description", "chapter_established", "status", "retired_chapter"}
        if not any(getattr(self, field) is not None for field in fields):
            raise ValueError("至少需要提供一个要更新的字段")
        return self


class FactResponse(BaseModel):
    """事实读取模型:不设写入预算,历史数据可完整返回。"""

    id: int
    novel_id: int
    subject: str
    attribute: str
    value: str
    description: Optional[str] = None
    chapter_established: Optional[int] = None
    status: str
    retired_chapter: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class EventCreate(StrictWriteModel):
    """创建剧情事件。"""

    novel_id: int = Field(..., gt=0, description="所属小说ID")
    title: str = Field(..., min_length=1, max_length=200, description="事件标题")
    description: str = Field(..., min_length=1, max_length=MAX_EVENT_DESCRIPTION_CHARS, description="事件描述")
    story_day: int = Field(1, gt=0, description="故事内天数")
    chapter: Optional[int] = Field(None, gt=0, description="对应章节号")
    involved_characters: List[str] = Field(
        default_factory=list,
        max_length=MAX_INVOLVED_CHARACTERS,
        description="关联角色名列表",
    )
    foreshadowing: Optional[str] = Field(None, max_length=MAX_FORESHADOWING_CHARS, description="埋下的伏笔/线索")
    status: Optional[str] = Field(None, pattern="^(planned|occurred)$", description="planned 或 occurred")

    @model_validator(mode="after")
    def validate_character_names(self):
        """限制角色名条目长度,防止单条名字制造无界上下文。"""
        for name in self.involved_characters:
            if not 1 <= len(name) <= 100:
                raise ValueError("关联角色名长度必须在 1 到 100 之间")
        return self


class EventUpdate(StrictWriteModel):
    """更新剧情事件。"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1, max_length=MAX_EVENT_DESCRIPTION_CHARS)
    story_day: Optional[int] = Field(None, gt=0)
    chapter: Optional[int] = Field(None, gt=0)
    involved_characters: Optional[List[str]] = Field(None, max_length=MAX_INVOLVED_CHARACTERS)
    foreshadowing: Optional[str] = Field(None, max_length=MAX_FORESHADOWING_CHARS)
    status: Optional[str] = Field(None, pattern="^(planned|occurred)$")

    @model_validator(mode="after")
    def validate_update_fields(self):
        """至少提供一个业务字段,避免空更新被误认为成功。"""
        fields = {
            "title", "description", "story_day", "chapter",
            "involved_characters", "foreshadowing", "status",
        }
        if not any(getattr(self, field) is not None for field in fields):
            raise ValueError("至少需要提供一个要更新的字段")
        return self

    @model_validator(mode="after")
    def validate_character_names(self):
        """限制角色名条目长度。"""
        if self.involved_characters is not None:
            for name in self.involved_characters:
                if not 1 <= len(name) <= 100:
                    raise ValueError("关联角色名长度必须在 1 到 100 之间")
        return self


class EventResponse(BaseModel):
    """事件读取模型。"""

    id: int
    novel_id: int
    title: str
    description: str
    story_day: int
    chapter: Optional[int] = None
    involved_characters: List[str] = []
    foreshadowing: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
