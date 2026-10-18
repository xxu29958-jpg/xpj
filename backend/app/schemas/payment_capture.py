"""Parsed evidence and explicit decisions; raw notification bodies stay on device."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import PositiveMoneyMinor


class PaymentCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["expense", "repayment", "refund", "unknown"]
    amount_minor: PositiveMoneyMinor | None = None
    field: Literal["title", "text", "bigText", "subText"]
    evidence: str = Field(min_length=1, max_length=64)


class PaymentCaptureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notification_key: str = Field(min_length=1, max_length=512)
    source: str = Field(min_length=1, max_length=32)
    captured_at: datetime
    original_currency: str = Field(min_length=3, max_length=3)
    original_amount_minor: PositiveMoneyMinor | None = None
    merchant: str | None = Field(default=None, max_length=255)
    suggested_kind: Literal["expense", "repayment", "review"]
    parser_version: str = Field(min_length=1, max_length=64)
    candidates: list[PaymentCandidate] = Field(default_factory=list, max_length=24)


class PaymentCaptureDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(ge=1)
    kind: Literal["expense", "repayment", "dismissed"]
    original_currency: str = Field(min_length=3, max_length=3)
    original_amount_minor: PositiveMoneyMinor | None = None
    merchant: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=255)


class RepaymentCorrectionVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    debt_row_version: int = Field(ge=1)
    source_expense_row_version: int | None = Field(default=None, ge=1)
    source_offset_row_version: int | None = Field(default=None, ge=1)


class RepaymentAsExpense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=255)
    notification_key: str | None = Field(default=None, min_length=1, max_length=512)
    correction_versions: RepaymentCorrectionVersions | None = None


class PaymentCaptureResponse(BaseModel):
    public_id: str
    row_version: int
    source: str
    captured_at: datetime
    original_currency: str
    original_amount_minor: PositiveMoneyMinor | None
    merchant: str | None
    kind: str
    parser_version: str
    candidates: list[PaymentCandidate]
    expense_id: int | None = None
    expense_public_id: str | None
    repayment_public_id: str | None
    decisions: list[dict]
