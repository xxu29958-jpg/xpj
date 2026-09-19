"""Original observations and explicit same-bill attachment commands."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso


class OriginalHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_id: int
    public_id: str
    row_version: int
    state: Literal["none", "cleaned", "missing", "corrupt", "unverified", "verified", "unreadable"]
    expected_sha256: str | None = None
    observed_sha256: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    checked_at: datetime

    @field_serializer("checked_at")
    def serialize_checked_at(self, value: datetime) -> str:
        return to_iso(value)


class OriginalVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(strict=True, gt=0)
    reviewed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OriginalCommandReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["verify_original", "replenish_original", "retry_original_cleanup", "cancel_original_cleanup"]
    expense_id: int
    public_id: str
    row_version: int
    sha256: str | None
    accepted_at: datetime

    @field_serializer("accepted_at")
    def serialize_accepted_at(self, value: datetime) -> str:
        return to_iso(value)
