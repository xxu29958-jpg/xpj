"""ADR-0049 §杠杆③ NLS repayment-capture inbox (slice 3a).

The Android NotificationListenerService classifies a payment notification as a
*repayment* for an external revolving debt (花呗 / 借呗 / 白条 / 京东 / 美团月付 /
银行卡) and posts it as a PENDING :class:`RepaymentDraft`. This module is the
service face:

* :func:`create_repayment_draft` — content+identity-deduped capture (mirrors the
  expense ``create_notification_draft``: a re-posted notification returns the
  existing draft, never a twin). Original currency is retained; conversion is
  deferred to explicit confirmation.
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

ACCOUNT-SCOPED, not just tenant-scoped (§8 / privacy): a repayment capture is personal (one
member's phone payment notification). Every read/lock of a specific draft (list, confirm/dismiss
lock, replay) filters ``created_by_account_id == actor_account_id`` so a shared-ledger member
can't see or act on another's captures — mirroring the account-scoped /web audit
(``list_repayment_draft_audit_for_account``) and learning matcher; a ledger-only scope leaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, Expense, PaymentCapture, RepaymentDraft
from app.schemas import (
    RepaymentDraftCreateRequest,
    RepaymentDraftListResponse,
    RepaymentDraftResponse,
)
from app.schemas.payment_capture import RepaymentCorrectionVersions
from app.services.debt_service._repayment_correction_context import repayment_correction_versions
from app.services.debt_service._repayment_draft_match import (
    RepaymentMatchCandidate,
    list_repayment_match_candidates,
    suggest_debt_for_draft,
)


def _corrected_expense_id(draft: RepaymentDraft) -> int | None:
    db = object_session(draft)
    if db is None or draft.status not in {"dismissed", "confirmed"}:
        return None
    return db.scalar(select(Expense.id).join(PaymentCapture, Expense.public_id == PaymentCapture.expense_public_id)
        .where(PaymentCapture.tenant_id == draft.tenant_id, PaymentCapture.actor_account_id == draft.created_by_account_id,
            PaymentCapture.repayment_public_id == draft.public_id, PaymentCapture.kind == "expense",
            Expense.tenant_id == draft.tenant_id))


def repayment_draft_response(
    draft: RepaymentDraft, *, suggested_debt_public_id: str | None = None
) -> RepaymentDraftResponse:
    # ``suggested_debt_public_id`` is the §杠杆③ slice-3b inbox match — supplied ONLY by the
    # list path for a pending draft (ephemeral, never stored). Every other caller (create /
    # confirm / dismiss responses, the confirm idempotency-replay re-serialize) returns a
    # draft with no suggestion: a freshly-captured draft is for the NLS poster (which never
    # uses the match) and a resolved draft is already linked.
    return RepaymentDraftResponse(
        corrected_expense_id=_corrected_expense_id(draft),
        correction_versions=(repayment_correction_versions(object_session(draft), draft)
            if object_session(draft) is not None and _corrected_expense_id(draft) is None else None),
        public_id=draft.public_id,
        source=draft.source,
        amount_cents=draft.amount_cents,
        home_currency_code=draft.home_currency_code,
        original_currency_code=draft.original_currency_code or draft.home_currency_code,
        original_amount_minor=draft.original_amount_minor if draft.original_amount_minor is not None else draft.amount_cents,
        merchant_label=draft.merchant_label,
        captured_at=draft.captured_at,
        status=draft.status,
        accounting_time=draft.accounting_time_snapshot,
        suggested_debt_public_id=suggested_debt_public_id,
        committed_debt_public_id=draft.committed_debt_public_id,
        committed_repayment_public_id=draft.committed_repayment_public_id,
        source_expense_public_id=draft.source_expense_public_id,
        source_expense_requires_review=(draft.source_expense_public_id is not None
            and draft.source_expense_row_version is None and draft.status == "pending"),
        created_at=draft.created_at,
        resolved_at=draft.resolved_at,
    )


def get_repayment_draft_response(
    db: Session, *, tenant_id: str, actor_account_id: int, public_id: str
) -> RepaymentDraftResponse:
    """Serialize one account-scoped draft (confirm idempotency-replay path).

    The replay HIT is always the actor's own confirm intent, so the ``created_by_account_id``
    filter never bites here — it keeps the uniform account-scope invariant (§8 / privacy)."""
    draft = db.scalar(
        ledger_scoped_select(RepaymentDraft, tenant_id)
        .where(RepaymentDraft.created_by_account_id == actor_account_id)
        .where(RepaymentDraft.public_id == public_id)
        .limit(1)
    )
    if draft is None:
        raise AppError("repayment_draft_not_found", status_code=404)
    return repayment_draft_response(draft)


def create_repayment_draft(db: Session, *, payload: RepaymentDraftCreateRequest,
        tenant_id: str, actor_account_id: int) -> RepaymentDraft:
    from app.services.payment_capture_service import capture_legacy_repayment

    return capture_legacy_repayment(db, payload, tenant_id=tenant_id, actor_account_id=actor_account_id)


def list_repayment_drafts(
    db: Session, *, tenant_id: str, actor_account_id: int, status: str | None = None
) -> RepaymentDraftListResponse:
    # Account-scoped (§8 / privacy, see module docstring): the inbox shows ONLY the actor's own.
    statement = ledger_scoped_select(RepaymentDraft, tenant_id).where(
        RepaymentDraft.created_by_account_id == actor_account_id
    )
    if status is not None:
        statement = statement.where(RepaymentDraft.status == status)
    statement = statement.order_by(RepaymentDraft.created_at.desc(), RepaymentDraft.id.desc())
    drafts = list(db.scalars(statement))
    # §杠杆③ slice 3b: suggest a target Debt for each PENDING draft (ephemeral — recomputed
    # here, never stored). Fetch the repayable candidate set once (only when there is a
    # pending draft to match) and run the pure matcher per pending draft; a resolved /
    # dismissed draft carries no suggestion.
    has_pending = any(draft.status == "pending" for draft in drafts)
    candidates = list_repayment_match_candidates(db, tenant_id=tenant_id) if has_pending else []
    return RepaymentDraftListResponse(
        items=[
            repayment_draft_response(
                draft,
                suggested_debt_public_id=(
                    suggest_debt_for_draft(
                        db,
                        account_id=draft.created_by_account_id,
                        source=draft.source,
                        merchant_label=draft.merchant_label,
                        amount_cents=draft.amount_cents,
                        candidates=candidates,
                    )
                    if draft.status == "pending" and draft.amount_cents is not None
                    else None
                ),
            )
            for draft in drafts
        ]
    )


@dataclass(frozen=True)
class RepaymentDraftAuditRow:
    """One NLS repayment capture reduced to the actionable /web review view.

    This is not the API ``RepaymentDraftResponse``: it adds resolved Debt labels and the
    feasible target set with each Debt's OCC row-version token. ``linked_debt_label`` is the
    committed Debt's raw ``counterparty_label`` (only meaningful when ``status``
    ``confirmed``; ``None`` = the Debt has no label → the route applies its fallback name).
    ``has_suggestion`` + ``suggested_debt_*`` carry a pending draft's ephemeral server
    suggestion. UI prose and fallback names remain in the route (§1: services do not write
    UI copy)."""

    source: str
    amount_cents: int | None
    home_currency_code: str
    merchant_label: str | None
    captured_at: datetime
    status: str
    linked_debt_label: str | None
    has_suggestion: bool
    suggested_debt_label: str | None
    public_id: str = ""
    suggested_debt_public_id: str | None = None
    target_debts: tuple[RepaymentMatchCandidate, ...] = ()
    original_currency_code: str | None = None
    original_amount_minor: int | None = None
    committed_debt_public_id: str | None = None
    resolved_at: datetime | None = None
    source_expense_public_id: str | None = None
    source_expense_requires_review: bool = False
    source_expense_id: int | None = None
    corrected_expense_id: int | None = None
    correction_versions: RepaymentCorrectionVersions | None = None


def _debt_counterparty_labels(db: Session, public_ids: set[str]) -> dict[str, str | None]:
    """Resolve Debt ``public_id`` → raw ``counterparty_label`` for the audit's 关联债 /
    suggested-provenance names. ``public_id`` is globally unique on ``Debt``, so one
    ``IN`` query resolves labels across ledgers. Cross-tenant-safe: every id here came from
    the account's OWN drafts (a committed Debt it confirmed, or a suggestion from the
    draft's own tenant), so the account already participates in those ledgers — no leak."""
    if not public_ids:
        return {}
    rows = db.execute(select(Debt.public_id, Debt.counterparty_label).where(Debt.public_id.in_(public_ids))).all()
    return dict(rows)


def list_repayment_draft_audit_for_account(
    db: Session, *, account_id: int, tenant_id: str | None = None, public_id: str | None = None
) -> list[RepaymentDraftAuditRow]:
    """Build the account-scoped repayment review and audit rows for Web.

    Repayment captures are personal (your phone's payment notifications), so the web audit
    shows only ``created_by_account_id == account_id``. Web supplies ``tenant_id`` so every
    actionable row also belongs to the selected ledger; the optional ``None`` keeps the
    account-wide service form available for non-mutating audit callers. For each PENDING
    draft, the suggestion is recomputed (§8) and feasible targets carry current row versions
    for the browser confirm command. Resolved rows retain their linked Debt label as history."""
    statement = select(RepaymentDraft).where(RepaymentDraft.created_by_account_id == account_id)
    if tenant_id is not None:
        statement = statement.where(RepaymentDraft.tenant_id == tenant_id)
    if public_id is not None:
        statement = statement.where(RepaymentDraft.public_id == public_id)
    drafts = list(
        db.scalars(
            statement.order_by(
                RepaymentDraft.created_at.desc(),
                RepaymentDraft.id.desc(),
            )
        )
    )
    candidates_by_tenant: dict[str, list] = {}
    suggested_by_draft: dict[int, str | None] = {}
    referenced: set[str] = set()
    for draft in drafts:
        if draft.status == "pending":
            if draft.tenant_id not in candidates_by_tenant:
                candidates_by_tenant[draft.tenant_id] = list_repayment_match_candidates(db, tenant_id=draft.tenant_id)
            suggested = suggest_debt_for_draft(
                db,
                account_id=draft.created_by_account_id,
                source=draft.source,
                merchant_label=draft.merchant_label,
                amount_cents=draft.amount_cents,
                candidates=candidates_by_tenant[draft.tenant_id],
            ) if draft.amount_cents is not None else None
            suggested_by_draft[draft.id] = suggested
            if suggested is not None:
                referenced.add(suggested)
        elif draft.status == "confirmed" and draft.committed_debt_public_id is not None:
            referenced.add(draft.committed_debt_public_id)
    labels = _debt_counterparty_labels(db, referenced)
    sources = _audit_source_expenses(db, drafts)
    return [
        _repayment_audit_row(draft, suggested_by_draft.get(draft.id), labels,
            candidates_by_tenant.get(draft.tenant_id, []), sources.get((draft.tenant_id, draft.source_expense_public_id)))
        for draft in drafts
    ]


def _audit_source_expenses(db: Session, drafts: list[RepaymentDraft]) -> dict[tuple[str, str], int]:
    source_ids = {draft.source_expense_public_id for draft in drafts if draft.source_expense_public_id}
    if not source_ids:
        return {}
    return {(tenant, source): identifier for tenant, source, identifier in db.execute(
        select(Expense.tenant_id, Expense.public_id, Expense.id).where(
            Expense.tenant_id.in_({draft.tenant_id for draft in drafts}), Expense.public_id.in_(source_ids)))}


def _repayment_audit_row(draft: RepaymentDraft, suggested_id: str | None, labels: dict[str, str | None],
    candidates: list[RepaymentMatchCandidate], source_expense_id: int | None) -> RepaymentDraftAuditRow:
    """Project captured money separately from eligible targets and a resolved fact's label."""
    committed_id = draft.committed_debt_public_id if draft.status == "confirmed" else None
    return RepaymentDraftAuditRow(
        source=draft.source,
        amount_cents=draft.amount_cents,
        home_currency_code=draft.home_currency_code,
        original_currency_code=draft.original_currency_code or draft.home_currency_code,
        original_amount_minor=draft.original_amount_minor if draft.original_amount_minor is not None else draft.amount_cents,
        merchant_label=draft.merchant_label,
        captured_at=draft.captured_at,
        status=draft.status,
        linked_debt_label=labels.get(committed_id) if committed_id else None,
        has_suggestion=suggested_id is not None,
        suggested_debt_label=labels.get(suggested_id) if suggested_id else None,
        public_id=draft.public_id,
        committed_debt_public_id=committed_id,
        resolved_at=draft.resolved_at,
        source_expense_public_id=draft.source_expense_public_id,
        source_expense_id=source_expense_id,
        corrected_expense_id=_corrected_expense_id(draft),
        correction_versions=(repayment_correction_versions(object_session(draft), draft)
            if object_session(draft) is not None and _corrected_expense_id(draft) is None else None),
        source_expense_requires_review=(draft.source_expense_public_id is not None
            and draft.source_expense_row_version is None and draft.status == "pending"),
        suggested_debt_public_id=suggested_id,
        # Review can correct the captured amount. Suggestions remain amount-aware;
        # the shared confirmation command checks the reviewed amount against remaining.
        target_debts=tuple(candidates) if draft.status == "pending" else (),
    )
