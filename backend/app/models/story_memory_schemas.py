"""大纲、实体和状态命令使用显式版本及幂等身份。"""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
TextValue = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class StrictMemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInput(StrictMemoryModel):
    revision_id: UUID
    quote: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0, strict=True)


class MemoryCommandInput(StrictMemoryModel):
    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    novel_lifecycle_id: str = Field(min_length=1, max_length=32)


class EntityInput(MemoryCommandInput):
    name: Name
    description: str = Field("", max_length=500)
    kind: Literal["character", "item", "location", "organization"]


class OutlineInput(MemoryCommandInput):
    parent_id: UUID | None = None
    kind: Literal["volume", "chapter", "scene"]
    plot_status: Literal["planned", "occurred"]
    chapter_number: int | None = Field(None, gt=0, strict=True)
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    conflict: str = Field("", max_length=2000)
    outcome: str = Field("", max_length=2000)
    source_refs: list[SourceInput] = Field(default_factory=list, max_length=20)


class StateInput(MemoryCommandInput):
    entity_id: UUID
    attribute: Name
    value: TextValue
    value_entity_id: UUID | None = None
    effective_chapter: int = Field(gt=0, strict=True)
    source_refs: list[SourceInput] = Field(default_factory=list, max_length=20)


class DecisionInput(MemoryCommandInput):
    action: Literal["confirm", "reject", "revoke"]
    reason: str = Field("", max_length=1000)


class ExtractionInput(MemoryCommandInput):
    source_revision_id: UUID


class ResolveInput(MemoryCommandInput):
    source_refs: list[SourceInput] = Field(default_factory=list, max_length=20)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
