"""Bounded timestamp literals; full notification bodies never enter this contract."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.receipt_parse_time import is_time_fragment


class NotificationTimeFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(pattern=r"^(title|text|bigText|subText)$")
    literal: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=32)

    @model_validator(mode="after")
    def timestamp_only(self):
        if not is_time_fragment(self.literal, self.label):
            raise ValueError("Only an extracted timestamp and its known time label are accepted")
        return self


class NotificationTimeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_timezone: str | None = Field(default=None, max_length=64)
    fragments: list[NotificationTimeFragment] = Field(default_factory=list, max_length=8)
    truncated: bool = False
