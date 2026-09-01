"""DTO conversion for sender and receiver views — privacy-preserving."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from app.models import BillSplitInvitation
from app.services.identity_service import DEFAULT_ACCOUNT_NAME

UNKNOWN_SENDER_DISPLAY_NAME = "未设置姓名的发起人"


def receiver_sender_presentation(snapshot_name: str, visible_ledger_name: str = "") -> tuple[str, str]:
    """Build an honest receiver-facing sender label from authorized facts."""
    name = (snapshot_name or "").strip()
    ledger_name = (visible_ledger_name or "").strip()
    if not name or name == DEFAULT_ACCOUNT_NAME:
        if ledger_name:
            return f"来自「{ledger_name}」的成员", ""
        return UNKNOWN_SENDER_DISPLAY_NAME, ""
    return name, f"来自「{ledger_name}」" if ledger_name else ""


class _BillSplitCommonPayload(TypedDict):
    public_id: str
    status: str
    amount_cents: int
    home_currency_code: str
    original_currency_code: str | None
    original_amount_minor: int | None
    exchange_rate_to_cny: Decimal | None
    exchange_rate_date: datetime | None
    exchange_rate_source: str | None
    merchant_snapshot: str | None
    category_suggestion: str | None
    expense_time_snapshot: datetime | None
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None
    rejected_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason_code: str | None
    expired_at: datetime | None


class BillSplitSentPayload(_BillSplitCommonPayload):
    receiver_account_id: int
    receiver_display_name_snapshot: str | None
    sender_expense_id: int
    source_impact_pending: bool


class BillSplitInboxPayload(_BillSplitCommonPayload):
    sender_account_id: int
    sender_display_name: str


def to_sent_response_dict(
    inv: BillSplitInvitation,
    *,
    source_impact_pending: bool = False,
) -> BillSplitSentPayload:
    """Sender view dict. Deliberately omits ``receiver_ledger_id``."""
    return {
        "public_id": inv.public_id,
        "status": inv.status,
        "amount_cents": inv.amount_cents,
        "home_currency_code": inv.home_currency_code,
        "original_currency_code": inv.original_currency_code,
        "original_amount_minor": inv.original_amount_minor,
        "exchange_rate_to_cny": inv.exchange_rate_to_cny,
        "exchange_rate_date": inv.exchange_rate_date,
        "exchange_rate_source": inv.exchange_rate_source,
        "merchant_snapshot": inv.merchant_snapshot,
        "category_suggestion": inv.category_suggestion,
        "expense_time_snapshot": inv.expense_time_snapshot,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
        "accepted_at": inv.accepted_at,
        "rejected_at": inv.rejected_at,
        "cancelled_at": inv.cancelled_at,
        "cancellation_reason_code": inv.cancellation_reason_code,
        "expired_at": inv.expired_at,
        "receiver_account_id": inv.receiver_account_id,
        "receiver_display_name_snapshot": inv.receiver_display_name_snapshot,
        "sender_expense_id": inv.sender_expense_id,
        "source_impact_pending": source_impact_pending,
    }


def to_inbox_response_dict(inv: BillSplitInvitation) -> BillSplitInboxPayload:
    """Receiver view dict. Deliberately omits sender's expense_id /
    ledger_id / member_id and receiver's own ledger_id (which is also
    private — receiver may have multiple ledgers)."""
    return {
        "public_id": inv.public_id,
        "status": inv.status,
        "amount_cents": inv.amount_cents,
        "home_currency_code": inv.home_currency_code,
        "original_currency_code": inv.original_currency_code,
        "original_amount_minor": inv.original_amount_minor,
        "exchange_rate_to_cny": inv.exchange_rate_to_cny,
        "exchange_rate_date": inv.exchange_rate_date,
        "exchange_rate_source": inv.exchange_rate_source,
        "merchant_snapshot": inv.merchant_snapshot,
        "category_suggestion": inv.category_suggestion,
        "expense_time_snapshot": inv.expense_time_snapshot,
        "expires_at": inv.expires_at,
        "created_at": inv.created_at,
        "accepted_at": inv.accepted_at,
        "rejected_at": inv.rejected_at,
        "cancelled_at": inv.cancelled_at,
        "cancellation_reason_code": inv.cancellation_reason_code,
        "expired_at": inv.expired_at,
        "sender_account_id": inv.sender_account_id,
        "sender_display_name": receiver_sender_presentation(inv.sender_display_name)[0],
    }
