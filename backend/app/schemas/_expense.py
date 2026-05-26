"""Expense surface: upload, manual create, draft, items, splits, OCR retry.

The big one — every request body and response shape a client hits when
working with a single expense (or a paginated list of them) lives here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.services.time_service import to_iso

ExpenseItemKind = Literal["product", "discount", "tax", "service_fee"]
ItemsSumStatus = Literal["matched", "mismatch_known", "mismatch_acknowledged", "no_items"]

__all__ = [
    "ConfirmedExpenseBatchUpdateRequest",
    "ConfirmedExpenseBatchUpdateResponse",
    "ExpenseConfirmRequest",
    "ExpenseItemRequest",
    "ExpenseItemReplaceRequest",
    "ExpenseItemResponse",
    "ExpenseItemsResponse",
    "ExpenseManualCreateRequest",
    "ExpenseMarkNotDuplicateRequest",
    "ExpenseOcrRetryRequest",
    "ExpenseRecognizeTextRequest",
    "ExpenseRejectRequest",
    "ExpenseResponse",
    "PendingCategorySuggestionResponse",
    "PendingDuplicateCandidateResponse",
    "ExpenseSplitReplaceRequest",
    "ExpenseSplitRequest",
    "ExpenseSplitResponse",
    "ExpenseSplitsResponse",
    "ExpenseUpdateRequest",
    "NotificationDraftCreateRequest",
    "OcrRetryResponse",
    "PaginatedExpensesResponse",
    "UploadResponse",
]


class UploadResponse(BaseModel):
    id: int
    public_id: str
    status: str
    message: str
    image_hash: str
    thumbnail_path: str | None
    duplicate_status: str
    duplicate_of_id: int | None
    upload_size_bytes: int
    duration_ms: int
    timing_ms: dict[str, int] = Field(default_factory=dict)


class ExpenseManualCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_cents: int | None = Field(default=None, ge=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, ge=0)
    spent_at: datetime | None = None
    original_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount_minor: int | None = Field(default=None, ge=0)
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    expense_time: datetime | None = None
    tags: str | None = None
    value_score: int | None = Field(default=None, ge=1, le=5)
    regret_score: int | None = Field(default=None, ge=1, le=5)


class NotificationDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    amount_cents: int | None = Field(default=None, ge=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, ge=0)
    spent_at: datetime | None = None
    original_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount_minor: int | None = Field(default=None, ge=0)
    merchant: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    expense_time: datetime | None = None


class ExpenseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime
    amount_cents: int | None = Field(default=None, ge=0)
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: Decimal | None = Field(default=None, ge=0)
    spent_at: datetime | None = None
    original_currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount_minor: int | None = Field(default=None, ge=0)
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    expense_time: datetime | None = None
    tags: str | None = None
    value_score: int | None = Field(default=None, ge=1, le=5)
    regret_score: int | None = Field(default=None, ge=1, le=5)


class ExpenseConfirmRequest(BaseModel):
    """ADR-0038 PR-2b: ``POST /api/expenses/{id}/confirm`` body.

    ``expected_updated_at`` is the optimistic-concurrency token client
    last saw on the expense; service-layer ``confirm_expense`` atomic
    ``UPDATE WHERE updated_at = expected_updated_at`` rejects stale
    writes with 409. Confirming an already-confirmed row remains
    idempotent (200) regardless of the token — confirmed is terminal.
    """

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class ExpenseRejectRequest(BaseModel):
    """ADR-0038 PR-2b: ``POST /api/expenses/{id}/reject`` body — same
    contract as ExpenseConfirmRequest; ``rejected`` is also terminal."""

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class ExpenseMarkNotDuplicateRequest(BaseModel):
    """ADR-0038 PR-2b: ``POST /api/expenses/{id}/mark-not-duplicate``."""

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class ExpenseOcrRetryRequest(BaseModel):
    """ADR-0038 PR-2c: ``POST /api/expenses/{id}/ocr/retry`` body."""

    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class ConfirmedExpenseBatchUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_ids: list[int] = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    tags: str | None = Field(default=None, max_length=500)


class ConfirmedExpenseBatchUpdateResponse(BaseModel):
    requested_count: int
    updated_count: int
    skipped_not_found: int
    skipped_not_confirmed: int


class ExpenseRecognizeTextRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)


class PendingCategorySuggestionResponse(BaseModel):
    decision_public_id: str
    category: str
    score: float
    sample_size: int
    algorithm_version: str


class PendingDuplicateCandidateResponse(BaseModel):
    decision_public_id: str
    candidate_id: int
    candidate_public_id: str | None = None
    score: float
    reasons: list[str] = Field(default_factory=list)
    algorithm_version: str


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    amount_cents: int | None
    home_amount_cents: int | None
    home_currency: str
    original_currency: str
    original_amount: Decimal | None
    fx_rate: Decimal | None
    fx_rate_date: date | None
    fx_source: str | None
    fx_status: str
    original_currency_code: str
    original_amount_minor: int | None
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_source: str | None
    merchant: str | None
    category: str
    note: str | None
    source: str
    image_path: str | None
    thumbnail_path: str | None
    image_hash: str | None
    raw_text: str | None
    confidence: float | None
    duplicate_status: str
    duplicate_of_id: int | None
    duplicate_reason: str | None
    tags: str | None
    value_score: int | None
    regret_score: int | None
    status: str
    expense_time: datetime | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    rejected_at: datetime | None
    image_deleted_at: datetime | None
    thumbnail_deleted_at: datetime | None
    category_suggestion: PendingCategorySuggestionResponse | None = None
    duplicate_candidates: list[PendingDuplicateCandidateResponse] = Field(
        default_factory=list
    )

    @field_serializer(
        "expense_time",
        "created_at",
        "updated_at",
        "confirmed_at",
        "rejected_at",
        "image_deleted_at",
        "thumbnail_deleted_at",
    )
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)

    @field_serializer("exchange_rate_to_cny", "original_amount", "fx_rate")
    def serialize_exchange_rate(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None


class ExpenseItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: ExpenseItemKind = "product"
    quantity_text: str | None = Field(default=None, max_length=64)
    unit_price_cents: int | None = Field(default=None, ge=0)
    amount_cents: int | None = None
    category: str | None = Field(default=None, max_length=64)
    raw_text: str | None = Field(default=None, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _amount_sign_by_kind(self) -> ExpenseItemRequest:
        # DB CHECK 也强制，但放在 schema 层让客户端直接拿 422 而不是 IntegrityError。
        if self.amount_cents is None:
            return self
        if self.kind == "discount":
            if self.amount_cents > 0:
                raise ValueError("discount line amount_cents must be <= 0")
        else:
            if self.amount_cents < 0:
                raise ValueError(f"{self.kind} line amount_cents must be >= 0")
        return self


class ExpenseItemReplaceRequest(BaseModel):
    items: list[ExpenseItemRequest] = Field(default_factory=list, max_length=200)


class ExpenseItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    position: int
    kind: ExpenseItemKind
    name: str
    quantity_text: str | None
    unit_price_cents: int | None
    amount_cents: int | None
    category: str
    raw_text: str | None
    confidence: float | None
    is_ocr_draft: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class ExpenseItemsResponse(BaseModel):
    expense_id: int
    parent_amount_cents: int | None
    items_total_amount_cents: int | None
    mismatch_cents: int | None
    items_sum_status: ItemsSumStatus
    items: list[ExpenseItemResponse]


class ExpenseSplitRequest(BaseModel):
    member_id: int = Field(ge=1)
    amount_cents: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=200)


class ExpenseSplitReplaceRequest(BaseModel):
    splits: list[ExpenseSplitRequest] = Field(default_factory=list, max_length=100)


class ExpenseSplitResponse(BaseModel):
    public_id: str
    position: int
    member_id: int
    account_name: str
    role: str
    amount_cents: int
    note: str | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("disabled_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class ExpenseSplitsResponse(BaseModel):
    expense_id: int
    parent_amount_cents: int | None
    splits_total_amount_cents: int | None
    mismatch_cents: int | None
    splits: list[ExpenseSplitResponse]


class PaginatedExpensesResponse(BaseModel):
    items: list[ExpenseResponse]
    page: int
    page_size: int
    total: int


class OcrRetryResponse(BaseModel):
    id: int
    status: str
    message: str
