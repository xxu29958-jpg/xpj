"""Original observations and explicit same-bill attachment commands."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

OriginalOperation = Literal["verify_original", "replenish_original", "retry_original_cleanup", "cancel_original_cleanup"]


class OriginalCleanupObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    reason: Literal["after_confirm", "confirmed_retention", "rejected_retention"]
    requested_at: datetime
    image: Literal["pending", "deleted", "cancelled"] | None
    thumbnail: Literal["pending", "deleted", "cancelled"] | None
    image_error: Literal["unlink_failed", "invalid_reference"] | None
    thumbnail_error: Literal["unlink_failed", "invalid_reference"] | None
    policy_enabled: bool

    @field_serializer("requested_at")
    def serialize_requested_at(self, value: datetime) -> str:
        return to_iso(value)


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
    cleanup: OriginalCleanupObservation | None = None
    cleanup_error: Literal["attachment_cleanup_invalid"] | None = None

    @field_serializer("checked_at")
    def serialize_checked_at(self, value: datetime) -> str:
        return to_iso(value)


class OriginalVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(strict=True, gt=0)
    reviewed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OriginalReplenishmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(strict=True, gt=0)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OriginalCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(strict=True, gt=0)
    request_id: UUID


class OriginalCommandReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: OriginalOperation
    expense_id: int
    public_id: str
    row_version: int
    sha256: str | None
    accepted_at: datetime
    cleanup_request_id: UUID | None = None
    cleanup_pending: bool | None = None

    @field_serializer("accepted_at")
    def serialize_accepted_at(self, value: datetime) -> str:
        return to_iso(value)
