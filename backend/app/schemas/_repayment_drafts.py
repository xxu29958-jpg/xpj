"""ADR-0049 §杠杆③ NLS repayment-capture payloads (slice 3a).

The Android NotificationListenerService classifies a payment notification as a
*repayment* and posts a ``RepaymentDraftCreateRequest`` — a PENDING capture, never
an auto-recorded fact (§8). The user reviews pending drafts and either CONFIRMS one
against a chosen open external/manual Debt (commits one ``Repayment`` — fold-changing,
so the confirm request carries ``expected_row_version``, the §2.1 stale-intent fence +
§3.6 fingerprint) or DISMISSES it.

Capture preserves original money. Human confirmation delegates FX freezing to
the existing repayment fact service using the captured payment time.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas._money import PositiveCanonicalDecimalInput, PositiveMoneyMinor
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
    bank_app / other — validated server-side). ``original_currency`` and
    ``original_amount`` carry captured money. Legacy ``amount_cents`` means CNY
    minor units, regardless of installation currency. The two forms are exclusive.
    ``notification_key`` is the per-post identity hash
    (SHA-256(``sbn.key`` | ``postTime``), 64 hex chars; absent → content+window dedup
    only) — the PRIMARY dedup axis so a re-posted notification does not twin the draft.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    # Legacy notification bodies explicitly denote CNY minor units.
    amount_cents: PositiveMoneyMinor | None = None
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: PositiveCanonicalDecimalInput | None = None
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
    original_currency: str | None = Field(default=None, min_length=3, max_length=3)
    original_amount: PositiveCanonicalDecimalInput | None = None


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
    amount_cents: PositiveMoneyMinor | None
    home_currency_code: str
    original_currency_code: str
    original_amount_minor: PositiveMoneyMinor
    merchant_label: str | None = None
    captured_at: datetime
    status: str
    # §杠杆③ slice 3b: the inbox's server-suggested target Debt (fuzzy counterparty_label +
    # amount). Ephemeral — recomputed every list, never stored — and populated ONLY for a
    # pending draft (a resolved/created draft has none). null = no confident match → the
    # user picks manually. A suggestion is not a fact (§8); confirm is still authoritative.
    suggested_debt_public_id: str | None = None
    committed_debt_public_id: str | None = None
    committed_repayment_public_id: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None

    @field_serializer("captured_at", "created_at", "resolved_at")
    def serialize_repayment_draft_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RepaymentDraftListResponse(BaseModel):
    items: list[RepaymentDraftResponse]
