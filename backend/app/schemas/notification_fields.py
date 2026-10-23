"""Bounded original field fragments; never a complete notification body."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationFieldFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["title", "text", "bigText", "subText"]
    literal: str = Field(min_length=1, max_length=96)


class NotificationFieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fragments: list[NotificationFieldFragment] = Field(default_factory=list, max_length=24)
    truncated: bool = False
