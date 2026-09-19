"""Original time intent and its frozen financial-date interpretation."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AccountingDateBasis = Literal[
    "instant_calendar", "user_date", "user_selected", "legacy_expense_time",
    "legacy_confirmed_at", "legacy_unknown", "legacy_offset_date",
]


class AccountingTimeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    precision: Literal["instant", "date_only"]
    calendar_revision: int = Field(strict=True, gt=0)
    user_local_date: date
    instant_utc: datetime | None = None
    source_timezone: str | None = None
    source_utc_offset_seconds: int | None = Field(default=None, strict=True, gt=-86400, lt=86400)
    accounting_date: date | None = None

    @field_validator("user_local_date", "accounting_date", mode="before")
    @classmethod
    def explicit_date(cls, value):
        if value is None or type(value) is date:
            return value
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        raise ValueError("日期必须使用 YYYY-MM-DD。")

    @field_validator("instant_utc", mode="before")
    @classmethod
    def explicit_instant(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("时刻必须包含明确的 UTC 偏移。")
        return value

    @model_validator(mode="after")
    def validate_precision(self):
        if self.precision == "date_only":
            if self.instant_utc is not None or self.source_utc_offset_seconds is not None:
                raise ValueError("仅日期输入不能包含时刻或 UTC 偏移。")
        elif self.instant_utc is None or self.instant_utc.utcoffset() is None:
            raise ValueError("精确时刻必须包含明确的 UTC 偏移。")
        return self


class AccountingTimeSnapshot(BaseModel):
    """Unknown historical evidence stays nullable; the containing receipt may omit it."""

    model_config = ConfigDict(frozen=True)

    precision: Literal["instant", "date_only", "unknown"] = "unknown"
    instant_utc: datetime | None = None
    user_local_date: date | None = None
    source_timezone: str | None = None
    source_utc_offset_seconds: int | None = None
    accounting_date: date | None = None
    calendar_revision: int | None = None
    basis: AccountingDateBasis | None = None

    @field_validator("instant_utc")
    @classmethod
    def utc_instant(cls, value):
        if value is not None:
            if value.utcoffset() is None:
                raise ValueError("已保存时刻必须具有 UTC 偏移。")
            return value.astimezone(UTC)
        return value
