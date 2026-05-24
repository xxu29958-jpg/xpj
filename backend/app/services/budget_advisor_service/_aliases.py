"""ADR-0036 alias resolver: real PII → opaque ids and back.

Every outbound payload that leaves the backend for the AI advisor must
swap real merchant names / account ids / expense ids for opaque
placeholders (``merchant_NNN`` / ``member_N`` / ``tx_NNN``). This module
owns those mappings; the records live in SQLite and are read back when
the AI response references a placeholder.

Concurrency: each ``get_or_create_*`` re-reads after collision (UNIQUE
``(tenant_id, anon_id)`` enforced at the DB level) — the second writer
wins by reading the row the first writer committed.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ledger_scope import ledger_filter
from app.models import (
    AiMemberAnonMap,
    AiMerchantAnonMap,
    AiTransactionTempIdMap,
)

_MAX_ALLOCATION_RETRIES = 5


def get_or_create_merchant_anon(
    db: Session, *, tenant_id: str, merchant_canonical: str
) -> str:
    """Return the existing ``merchant_NNN`` placeholder for the canonical
    merchant name in this tenant, allocating a new one on first sight."""

    canonical = (merchant_canonical or "").strip()
    if not canonical:
        return ""
    existing = db.scalar(
        select(AiMerchantAnonMap)
        .where(ledger_filter(AiMerchantAnonMap, tenant_id))
        .where(AiMerchantAnonMap.merchant_canonical == canonical)
        .limit(1)
    )
    if existing is not None:
        return existing.anon_id
    return _allocate(
        db,
        tenant_id=tenant_id,
        model=AiMerchantAnonMap,
        prefix="merchant",
        extra_kwargs={"merchant_canonical": canonical},
        existing_lookup=lambda: db.scalar(
            select(AiMerchantAnonMap)
            .where(ledger_filter(AiMerchantAnonMap, tenant_id))
            .where(AiMerchantAnonMap.merchant_canonical == canonical)
            .limit(1)
        ),
    )


def get_or_create_member_anon(
    db: Session, *, tenant_id: str, account_id: int
) -> str:
    """Return the existing ``member_N`` placeholder for this family
    member in this tenant, allocating on first sight."""

    existing = db.scalar(
        select(AiMemberAnonMap)
        .where(ledger_filter(AiMemberAnonMap, tenant_id))
        .where(AiMemberAnonMap.account_id == account_id)
        .limit(1)
    )
    if existing is not None:
        return existing.anon_id
    return _allocate(
        db,
        tenant_id=tenant_id,
        model=AiMemberAnonMap,
        prefix="member",
        extra_kwargs={"account_id": account_id},
        existing_lookup=lambda: db.scalar(
            select(AiMemberAnonMap)
            .where(ledger_filter(AiMemberAnonMap, tenant_id))
            .where(AiMemberAnonMap.account_id == account_id)
            .limit(1)
        ),
    )


def assign_transaction_temp_id(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    session_id: str,
) -> str:
    """Assign (or return existing) ``tx_NNN`` for an expense inside a
    specific AI advisor call session."""

    existing = db.scalar(
        select(AiTransactionTempIdMap)
        .where(ledger_filter(AiTransactionTempIdMap, tenant_id))
        .where(AiTransactionTempIdMap.session_id == session_id)
        .where(AiTransactionTempIdMap.expense_id == expense_id)
        .limit(1)
    )
    if existing is not None:
        return existing.temp_id

    seq = int(
        db.scalar(
            select(func.count())
            .select_from(AiTransactionTempIdMap)
            .where(ledger_filter(AiTransactionTempIdMap, tenant_id))
            .where(AiTransactionTempIdMap.session_id == session_id)
        )
        or 0
    )
    for attempt in range(_MAX_ALLOCATION_RETRIES):
        candidate = f"tx_{seq + 1 + attempt:03d}"
        row = AiTransactionTempIdMap(
            tenant_id=tenant_id,
            session_id=session_id,
            expense_id=expense_id,
            temp_id=candidate,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            re_check = db.scalar(
                select(AiTransactionTempIdMap)
                .where(ledger_filter(AiTransactionTempIdMap, tenant_id))
                .where(AiTransactionTempIdMap.session_id == session_id)
                .where(AiTransactionTempIdMap.expense_id == expense_id)
                .limit(1)
            )
            if re_check is not None:
                return re_check.temp_id
            continue
        return candidate
    raise RuntimeError("budget_advisor_aliases: failed to allocate tx temp id")


def resolve_merchant_anon(
    db: Session, *, tenant_id: str, anon_id: str
) -> str | None:
    """Reverse lookup: AI returned ``merchant_001``; what's the real
    canonical name to show the user? Returns None if unknown."""

    row = db.scalar(
        select(AiMerchantAnonMap)
        .where(ledger_filter(AiMerchantAnonMap, tenant_id))
        .where(AiMerchantAnonMap.anon_id == anon_id)
        .limit(1)
    )
    return row.merchant_canonical if row is not None else None


def resolve_member_anon(
    db: Session, *, tenant_id: str, anon_id: str
) -> int | None:
    """Reverse lookup for ``member_N`` → real ``account_id``."""

    row = db.scalar(
        select(AiMemberAnonMap)
        .where(ledger_filter(AiMemberAnonMap, tenant_id))
        .where(AiMemberAnonMap.anon_id == anon_id)
        .limit(1)
    )
    return row.account_id if row is not None else None


def resolve_transaction_temp_id(
    db: Session, *, tenant_id: str, session_id: str, temp_id: str
) -> int | None:
    """Reverse lookup for ``tx_NNN`` within a session → real expense_id."""

    row = db.scalar(
        select(AiTransactionTempIdMap)
        .where(ledger_filter(AiTransactionTempIdMap, tenant_id))
        .where(AiTransactionTempIdMap.session_id == session_id)
        .where(AiTransactionTempIdMap.temp_id == temp_id)
        .limit(1)
    )
    return row.expense_id if row is not None else None


def cleanup_session(
    db: Session, *, tenant_id: str, session_id: str
) -> int:
    """Drop all transaction temp ids for a finished AI session. Returns
    the number of rows removed. Merchant / member aliases persist across
    sessions (stable placeholders the user can recognise over time)."""

    deleted = db.execute(
        AiTransactionTempIdMap.__table__.delete()
        .where(AiTransactionTempIdMap.tenant_id == tenant_id)
        .where(AiTransactionTempIdMap.session_id == session_id)
    )
    return int(deleted.rowcount or 0)


def _allocate(
    db: Session,
    *,
    tenant_id: str,
    model,
    prefix: str,
    extra_kwargs: dict,
    existing_lookup,
) -> str:
    seq = int(
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(ledger_filter(model, tenant_id))
        )
        or 0
    )
    for attempt in range(_MAX_ALLOCATION_RETRIES):
        width = 3 if prefix == "merchant" else 1
        candidate = f"{prefix}_{seq + 1 + attempt:0{width}d}"
        row = model(tenant_id=tenant_id, anon_id=candidate, **extra_kwargs)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            re_check = existing_lookup()
            if re_check is not None:
                return re_check.anon_id
            continue
        return candidate
    raise RuntimeError(f"budget_advisor_aliases: failed to allocate {prefix} anon_id")
