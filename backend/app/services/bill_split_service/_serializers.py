"""DTO conversion for sender and receiver views — privacy-preserving."""

from __future__ import annotations

from typing import Any

from app.models import BillSplitInvitation


def to_sent_response_dict(inv: BillSplitInvitation) -> dict[str, Any]:
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
        "expired_at": inv.expired_at,
        "receiver_account_id": inv.receiver_account_id,
        "receiver_display_name_snapshot": inv.receiver_display_name_snapshot,
        "sender_expense_id": inv.sender_expense_id,
    }


def to_inbox_response_dict(inv: BillSplitInvitation) -> dict[str, Any]:
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
        "expired_at": inv.expired_at,
        "sender_account_id": inv.sender_account_id,
        "sender_display_name": inv.sender_display_name,
    }
