"""ADR-0049 §杠杆③ NLS repayment-capture payloads (slice 3a).

The Android NotificationListenerService classifies a payment notification as a
*repayment* and posts a ``RepaymentDraftCreateRequest`` — a PENDING capture, never
an auto-recorded fact (§8). The user reviews pending drafts and either CONFIRMS one
against a chosen open external/manual Debt (commits one ``Repayment`` — fold-changing,
so the confirm request carries ``expected_row_version``, the §2.1 stale-intent fence +
§3.6 fingerprint) or DISMISSES it.

CNY notifications carry the amount in home-currency minor units already, so there is no
[[0027]] FX freeze here (unlike ``RepaymentCreateRequest`` / ``DebtCreateRequest``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "RepaymentDraftConfirmRequest",
    "RepaymentDraftCreateRequest",
    "RepaymentDraftDismissRequest",
    "RepaymentDraftListResponse",
    "RepaymentDraftResponse",
]


class RepaymentDraftCreateRequest(BaseModel):
    """Post one NLS-captured repayment as a pending review draft (ADR-0049 §杠杆③).

    ``source`` is the capturing channel (alipay / jd / meituan / wechat / bank_sms /
    bank_app / other — validated server-side). ``amount_cents`` is home-currency minor
    units — the capture is home-currency ONLY (CNY notifications carry no FX), so the
    draft's home currency is set SERVER-SIDE from the configured home currency, NOT taken
    as a client input (a field whose only legal value is the constant home currency would
    fake multi-currency support it doesn't have; a real foreign-currency capture would add
    ``original_currency`` + ``original_amount`` — the record_repayment shape — instead).
    ``notification_key`` is the per-post identity hash
    (SHA-256(``sbn.key`` | ``postTime``), 64 hex chars; absent → content+window dedup
    only) — the PRIMARY dedup axis so a re-posted notification does not twin the draft.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    amount_cents: int = Field(gt=0)
    merchant_label: str | None = Field(default=None, max_length=255)
    captured_at: datetime | None = None
    notification_key: str | None = Field(default=None, max_length=512)


class RepaymentDraftConfirmRequest(BaseModel):
    """Confirm a pending repayment draft against a chosen Debt (ADR-0049 §杠杆③).

    ``target_debt_public_id`` is the open external/manual Debt the captured repayment
    pays down (the user picks it in slice 3a; slice 3b pre-selects a server match).
    Confirm commits one ``Repayment`` → fold-changing, so ``expected_row_version`` is
    the chosen Debt's §2.1 stale-intent token + §3.6 fingerprint component (REQUIRED).
    """

    model_config = ConfigDict(extra="forbid")

    target_debt_public_id: str = Field(min_length=1, max_length=36)
    expected_row_version: int


class RepaymentDraftDismissRequest(BaseModel):
    """Dismiss a pending repayment draft (ADR-0049 §杠杆③).

    A no-op body: dismiss targets the draft by path id and only succeeds while it is
    still ``pending`` (an already-dismissed draft is an idempotent success; a confirmed
    one is a ``state_conflict``). It commits no ``Repayment``, so no token.
    """

    model_config = ConfigDict(extra="forbid")


class RepaymentDraftResponse(BaseModel):
    public_id: str
    source: str
    amount_cents: int
    home_currency_code: str
    merchant_label: str | None = None
    captured_at: datetime
    status: str
    committed_debt_public_id: str | None = None
    committed_repayment_public_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    @field_serializer("captured_at", "created_at", "resolved_at")
    def serialize_repayment_draft_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RepaymentDraftListResponse(BaseModel):
    items: list[RepaymentDraftResponse]
