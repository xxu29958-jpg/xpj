"""Explicit Reference Library creation, before any financial use."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReferenceKind = Literal["category", "tag"]


class ReferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)


class ReferenceCreatedResponse(BaseModel):
    kind: ReferenceKind
    public_id: str
    name: str
    row_version: int
