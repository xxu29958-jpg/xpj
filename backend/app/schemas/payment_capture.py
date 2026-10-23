"""Parsed evidence and explicit decisions; raw notification bodies stay on device."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.schemas._money import PositiveMoneyMinor
from app.schemas._recognition_time import RecognitionTimeResponse
from app.schemas.notification_fields import NotificationFieldEvidence
from app.schemas.notification_time import NotificationTimeEvidence


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
    time_evidence: NotificationTimeEvidence | None = None
    field_evidence: NotificationFieldEvidence | None = None

    @model_validator(mode="after")
    def aware_capture_time(self):
        if self.captured_at.utcoffset() is None:
            raise ValueError("Notification delivery time must include its UTC offset")
        return self


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
    funds_account_versions: dict[str, int] = Field(default_factory=dict)
    fee_expense_versions: dict[int, int] = Field(default_factory=dict)


class RepaymentAsExpense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=255)
    notification_key: str | None = Field(default=None, min_length=1, max_length=512)
    correction_versions: RepaymentCorrectionVersions | None = None
    expense_currency: str | None = Field(default=None, min_length=3, max_length=3)
    expense_amount_minor: PositiveMoneyMinor | None = None

    @model_validator(mode="after")
    def reviewed_money_pair(self):
        if (self.expense_currency is None) != (self.expense_amount_minor is None):
            raise ValueError("实际消费金额与币种须一并核对")
        return self


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
    recognition_time: RecognitionTimeResponse | None = None

    @model_serializer(mode="wrap")
    def preserve_stored_response(self, handler):
        data = handler(self)
        if "recognition_time" not in self.model_fields_set:
            data.pop("recognition_time", None)
        return data
