"""Typed command and history contracts for confirmed Expense corrections."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas._expense import (
    ExpenseItemRequest,
    ExpenseResponse,
    ExpenseSplitRequest,
    ExpenseUpdateRequest,
)
from app.services.time_service import to_iso
from app.tag_text import validate_tags_fit_storage

__all__ = [
    "ConfirmedExpenseBatchUpdateRequest",
    "ConfirmedExpenseBatchUpdateResponse",
    "ExpenseCorrectionRequest",
    "ExpenseCorrectionResponse",
    "ExpenseRevisionListResponse",
    "ExpenseRevisionResponse",
]


class ConfirmedExpenseBatchUpdateRequest(BaseModel):
    """One reasoned category or tag correction across confirmed facts."""

    model_config = ConfigDict(extra="forbid")

    expense_ids: list[int] = Field(min_length=1, max_length=200)
    expected_row_version_by_id: dict[int, int] = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    tags: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=500)

    _tags_fit_mirror = field_validator("tags")(validate_tags_fit_storage)

    @field_validator("reason")
    @classmethod
    def _strip_batch_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("correction reason is required")
        return cleaned


class ConfirmedExpenseBatchUpdateResponse(BaseModel):
    requested_count: int
    updated_count: int
    skipped_not_found: int
    skipped_not_confirmed: int


class ExpenseCorrectionRequest(ExpenseUpdateRequest):
    """One explicit correction intent against a confirmed fact snapshot."""

    reason: str = Field(min_length=1, max_length=500)
    items: list[ExpenseItemRequest] | None = Field(default=None, max_length=200)
    splits: list[ExpenseSplitRequest] | None = Field(default=None, max_length=100)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("correction reason is required")
        return cleaned

    @model_validator(mode="after")
    def _requires_mutation_intent(self) -> ExpenseCorrectionRequest:
        if not (self.model_fields_set - {"expected_row_version", "reason"}):
            raise ValueError("at least one corrected field is required")
        return self


class ExpenseRevisionResponse(BaseModel):
    """Human-timeline evidence; snapshots stay server-authored JSON."""

    model_config = ConfigDict(extra="forbid")

    public_id: str
    revision_number: int
    change_kind: Literal["confirmed", "correction"]
    reason: str
    changed_fields: list[str]
    before: dict[str, Any] | None
    after: dict[str, Any]
    actor_account_name: str | None = None
    actor_device_name: str | None = None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        return to_iso(value)


class ExpenseCorrectionResponse(BaseModel):
    expense: ExpenseResponse
    revision: ExpenseRevisionResponse


class ExpenseRevisionListResponse(BaseModel):
    items: list[ExpenseRevisionResponse]
    page: int
    page_size: int
    total: int
    snapshot_revision: int
