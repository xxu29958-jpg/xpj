"""ADR-0049 §杠杆③ NLS repayment-capture inbox (slice 3a).

The Android NotificationListenerService classifies a payment notification as a
*repayment* for an external revolving debt (花呗 / 借呗 / 白条 / 京东 / 美团月付 /
银行卡) and posts it as a PENDING :class:`RepaymentDraft`. This module is the
service face:

* :func:`create_repayment_draft` — content+identity-deduped capture (mirrors the
  expense ``create_notification_draft``: a re-posted notification returns the
  existing draft, never a twin). Home-currency only — CNY notifications carry no
  [[0027]] FX freeze.
* :func:`list_repayment_drafts` — the review inbox (optionally filtered by status).
* :func:`confirm_repayment_draft` — records ONE ``Repayment`` on a user-chosen open
  external/manual Debt via :func:`record_repayment` (so the §2.1 parent-row lock,
  over-remaining check, and OCC stale-intent fence all apply unchanged), then latches
  the draft ``confirmed``. The draft row is locked ``FOR UPDATE`` and status-guarded so
  two confirms cannot each commit a repayment (§8 — capture is best-effort, the user's
  confirmation is the authoritative act, recorded exactly once).
* :func:`dismiss_repayment_draft` — latches a pending draft ``dismissed`` (idempotent if
  already dismissed; ``state_conflict`` if already confirmed).

Every draft is stored UNLINKED — the user picks the target Debt at confirm time. Slice 3b
adds a server-side fuzzy match (counterparty_label + amount → suggested Debt) that
:func:`list_repayment_drafts` computes EPHEMERALLY per pending draft and returns as
``RepaymentDraftResponse.suggested_debt_public_id`` (see :mod:`_repayment_draft_match`).
It is never stored on the draft: a Debt suggested at capture time can be cleared / voided /
created by review time, so the match is recomputed against current Debt state every list.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import RepaymentDraft
from app.schemas import (
    RepaymentCreateRequest,
    RepaymentDraftCreateRequest,
    RepaymentDraftListResponse,
    RepaymentDraftResponse,
)
from app.services.currency_common import home_currency_code
from app.services.debt_service._repayment import record_repayment
from app.services.debt_service._repayment_draft_match import (
    list_repayment_match_candidates,
    suggest_debt_public_id,
)
from app.services.time_service import ensure_utc, now_utc

# Capture channels (display label is for /web + provenance, not the dedup axis).
# 花呗/借呗 surface from Alipay; 白条 from 京东/京东金融; 美团月付 from 美团; plus
# WeChat credit-card repayments and bank repayment SMS. Extendable as the Android
# package allowlist grows.
REPAYMENT_DRAFT_SOURCE_LABELS = {
    "alipay": "支付宝",
    "jd": "京东",
    "meituan": "美团",
    "wechat": "微信",
    "bank_sms": "银行短信",
    "bank_app": "银行 App",
    "other": "其他",
}

_REPAYMENT_DRAFT_WINDOW_MINUTES = 30


def _clean_repayment_source(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_")
    if cleaned not in REPAYMENT_DRAFT_SOURCE_LABELS:
        raise AppError("notification_source_invalid", status_code=422)
    return cleaned


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _repayment_window_key(captured_at) -> str:
    when = ensure_utc(captured_at)
    minute = (when.minute // _REPAYMENT_DRAFT_WINDOW_MINUTES) * _REPAYMENT_DRAFT_WINDOW_MINUTES
    bucket = when.replace(minute=minute, second=0, microsecond=0)
    return bucket.isoformat()


def _repayment_draft_key(
    *,
    source: str,
    merchant: str | None,
    amount_cents: int,
    home_currency: str,
    captured_at,
    notification_key: str | None = None,
) -> str:
    # ``notification_key`` is the Android per-post identity (SHA-256(sbn.key|postTime)) —
    # the PRIMARY dedup axis (codex PR#20). Distinct posts → distinct drafts; the same
    # post re-sent → dedupe. Absent → "" reduces the key to content+window. The
    # "repayment_notification" prefix keeps this namespace disjoint from the expense
    # ``_notification_draft_key`` ("notification"), so a repayment and a same-amount
    # expense never collide.
    merchant_key = (merchant or "").strip()
    material = "|".join(
        [
            "repayment_notification",
            (notification_key or "").strip(),
            source,
            merchant_key.casefold(),
            str(amount_cents),
            (home_currency or "").strip().upper(),
            _repayment_window_key(captured_at),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def repayment_draft_response(
    draft: RepaymentDraft, *, suggested_debt_public_id: str | None = None
) -> RepaymentDraftResponse:
    # ``suggested_debt_public_id`` is the §杠杆③ slice-3b inbox match — supplied ONLY by the
    # list path for a pending draft (ephemeral, never stored). Every other caller (create /
    # confirm / dismiss responses, the confirm idempotency-replay re-serialize) returns a
    # draft with no suggestion: a freshly-captured draft is for the NLS poster (which never
    # uses the match) and a resolved draft is already linked.
    return RepaymentDraftResponse(
        public_id=draft.public_id,
        source=draft.source,
        amount_cents=draft.amount_cents,
        home_currency_code=draft.home_currency_code,
        merchant_label=draft.merchant_label,
        captured_at=draft.captured_at,
        status=draft.status,
        suggested_debt_public_id=suggested_debt_public_id,
        committed_debt_public_id=draft.committed_debt_public_id,
        committed_repayment_public_id=draft.committed_repayment_public_id,
        created_at=draft.created_at,
        resolved_at=draft.resolved_at,
    )


def get_repayment_draft_response(
    db: Session, *, tenant_id: str, public_id: str
) -> RepaymentDraftResponse:
    """Serialize one tenant-scoped draft (used by the confirm idempotency-replay path)."""
    draft = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.public_id == public_id)
        .limit(1)
    )
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    return repayment_draft_response(draft)


def create_repayment_draft(
    db: Session,
    *,
    payload: RepaymentDraftCreateRequest,
    tenant_id: str,
    actor_account_id: int,
) -> RepaymentDraft:
    """Capture one pending repayment draft, deduped per tenant (ADR-0049 §杠杆③).

    A re-posted notification (same identity/content/window) returns the existing draft
    rather than inserting a twin — same content-dedup contract as the expense
    notification-draft path, including the IntegrityError race fallback.
    """
    now = now_utc()
    source = _clean_repayment_source(payload.source)
    # §杠杆③ capture is home-currency ONLY (CNY notifications carry no FX, and confirm
    # records draft.amount_cents as home minor units). The home currency is a SERVER
    # concept, not a client input — set it from the configured home currency so the stored
    # value is always truthful and confirm can never reinterpret a foreign amount as home.
    # (A future foreign-currency capture would add original_currency/original_amount.)
    home_currency = home_currency_code()
    captured_at = ensure_utc(payload.captured_at) if payload.captured_at else now
    idempotency_key = _repayment_draft_key(
        source=source,
        merchant=payload.merchant_label,
        amount_cents=payload.amount_cents,
        home_currency=home_currency,
        captured_at=captured_at,
        notification_key=payload.notification_key,
    )
    existing = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id).where(
            RepaymentDraft.draft_idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing

    draft = RepaymentDraft(
        tenant_id=tenant_id,
        created_by_account_id=actor_account_id,
        source=source,
        amount_cents=payload.amount_cents,
        home_currency_code=home_currency,
        merchant_label=_clean_optional_text(payload.merchant_label),
        captured_at=captured_at,
        draft_idempotency_key=idempotency_key,
        status="pending",
        created_at=now,
    )
    db.add(draft)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            ledger_scoped_select(RepaymentDraft, tenant_id).where(
                RepaymentDraft.draft_idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing
        raise
    db.commit()
    db.refresh(draft)
    return draft


def list_repayment_drafts(
    db: Session, *, tenant_id: str, status: str | None = None
) -> RepaymentDraftListResponse:
    statement = ledger_scoped_select(RepaymentDraft, tenant_id)
    if status is not None:
        statement = statement.where(RepaymentDraft.status == status)
    statement = statement.order_by(
        RepaymentDraft.created_at.desc(), RepaymentDraft.id.desc()
    )
    drafts = list(db.scalars(statement))
    # §杠杆③ slice 3b: suggest a target Debt for each PENDING draft (ephemeral — recomputed
    # here, never stored). Fetch the repayable candidate set once (only when there is a
    # pending draft to match) and run the pure matcher per pending draft; a resolved /
    # dismissed draft carries no suggestion.
    has_pending = any(draft.status == "pending" for draft in drafts)
    candidates = (
        list_repayment_match_candidates(db, tenant_id=tenant_id) if has_pending else []
    )
    return RepaymentDraftListResponse(
        items=[
            repayment_draft_response(
                draft,
                suggested_debt_public_id=(
                    suggest_debt_public_id(
                        amount_cents=draft.amount_cents,
                        merchant_label=draft.merchant_label,
                        candidates=candidates,
                    )
                    if draft.status == "pending"
                    else None
                ),
            )
            for draft in drafts
        ]
    )


def _lock_pending_draft(db: Session, *, tenant_id: str, public_id: str) -> RepaymentDraft:
    """``SELECT ... FOR UPDATE`` a tenant-scoped draft; the row is the serialization
    point so two resolutions (confirm/dismiss) cannot both fire."""
    draft = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.public_id == public_id)
        .with_for_update()
        .limit(1)
    )
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    return draft


def confirm_repayment_draft(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    target_debt_public_id: str,
    expected_row_version: int,
    idempotency_key: str,
    commit: bool = False,
) -> RepaymentDraft:
    """Confirm a pending draft → record one ``Repayment`` on the chosen Debt (§杠杆③).

    The draft is locked first (status guard) so it claims the capture before any
    repayment is written: if a concurrent confirm already latched it, this raises
    ``state_conflict`` BEFORE :func:`record_repayment` runs, so the captured repayment
    is recorded exactly once. ``record_repayment`` enforces the external/manual guard,
    the §2.1 over-remaining check under the parent-Debt lock, and the OCC stale-intent
    fence on ``expected_row_version`` — a failure there rolls back the draft latch too
    (single transaction, ``commit=False``).
    """
    draft = _lock_pending_draft(db, tenant_id=tenant_id, public_id=public_id)
    if draft.status != "pending":
        # Already confirmed or dismissed — a second confirm cannot record again.
        raise AppError("state_conflict", status_code=409)

    result = record_repayment(
        db,
        tenant_id=tenant_id,
        public_id=target_debt_public_id,
        actor_account_id=actor_account_id,
        payload=RepaymentCreateRequest(
            amount_cents=draft.amount_cents,
            # The whole point of NLS capture is that it knows WHEN the repayment happened
            # (captured_at = the notification post time). Confirm may be days later, so pass
            # captured_at through as the repayment's paid_at instead of letting
            # record_repayment fall back to now() — otherwise a delayed review back-stamps
            # the debt history to review time. (The §6 projection keys off created_at, not
            # paid_at, so this only sharpens the user-facing payment time, never the velocity.)
            paid_at=draft.captured_at,
            expected_row_version=expected_row_version,
        ),
        idempotency_key=idempotency_key,
        commit=False,
    )

    draft.status = "confirmed"
    draft.committed_debt_public_id = target_debt_public_id
    draft.committed_repayment_public_id = result.repayment_public_id
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    db.flush()
    if commit:
        db.commit()
        db.refresh(draft)
    return draft


def dismiss_repayment_draft(
    db: Session,
    *,
    tenant_id: str,
    actor_account_id: int,
    public_id: str,
    commit: bool = False,
) -> RepaymentDraft:
    """Latch a pending draft ``dismissed`` (idempotent if already dismissed)."""
    draft = _lock_pending_draft(db, tenant_id=tenant_id, public_id=public_id)
    if draft.status == "dismissed":
        return draft  # idempotent: already dismissed
    if draft.status == "confirmed":
        raise AppError("state_conflict", status_code=409)

    draft.status = "dismissed"
    draft.resolved_at = now_utc()
    draft.resolved_by_account_id = actor_account_id
    db.flush()
    if commit:
        db.commit()
        db.refresh(draft)
    return draft
