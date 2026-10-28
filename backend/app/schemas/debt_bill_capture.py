"""Original capture and suggestion receipts, separate from the Debt result."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._debts import DebtBillParseResponse


class DebtBillCaptureReceipt(BaseModel):
    public_id: str
    creation_key: str
    capture_key: str
    row_version: int
    input_sha256: str
    image_hash: str


class DebtBillParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_row_version: int = Field(gt=0)


class DebtBillParseOutcome(BaseModel):
    public_id: str
    attempt_key: str
    row_version: int
    status: Literal["succeeded", "failed"]
    provider: str
    suggestion: DebtBillParseResponse | None = None
    error_code: str | None = None
    completed_at: datetime


class DebtBillCaptureResponse(DebtBillCaptureReceipt):
    status: Literal["pending", "confirmed", "rejected"]
    file_name: str
    media_type: str
    image_size_bytes: int
    original_state: Literal["verified", "cleaned", "missing", "corrupt", "unreadable"]
    image_evidence: dict | None
    adopted_debt_public_id: str | None
    parse_outcome: DebtBillParseOutcome | None
    created_at: datetime
    confirmed_at: datetime | None
    rejected_at: datetime | None


class DebtBillCaptureListResponse(BaseModel):
    captures: list[DebtBillCaptureResponse]
