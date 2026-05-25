"""v1.2 learning feedback service.

Public surface:

* :func:`record_decision` — algorithm emits a suggestion → row in
  ``algorithm_decisions``. The ledger is never touched here.
* :func:`record_event` — user reacted to a decision (accept / reject /
  edit / ignore) OR made a manual override with no prior suggestion.
* :func:`supersede_decision` — when a newer version of the same
  algorithm produces a fresh suggestion for the same subject, the old
  decision is marked ``superseded`` and the new id is linked in
  ``superseded_by_id``.
* :func:`recent_events_for_subject` / :func:`active_decision_for_subject`
  — read-side helpers the suggestion / scoring services use to look up
  the user's prior reactions when deciding whether to suggest again.

Design discipline:

* Both tables are tenant-scoped; every public function takes
  ``tenant_id`` explicitly (no implicit "current tenant" magic).
* Payloads are dicts going in, JSON strings going out. We use
  ``json.dumps(..., sort_keys=True, ensure_ascii=False)`` so the same
  logical payload always serialises identically — important for hash
  / dedup queries on top.
* Nothing here decides *what* an algorithm suggests; that lives in the
  per-algorithm service modules (category / duplicate / recurring / ...
  forthcoming under P1+). This module is the boring write-side.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AlgorithmDecision, Expense, LedgerLearningEvent, OcrFact
from app.services.learning_service._algorithm_registry import (
    ALGORITHM_TYPES,
    BUDGET_SUGGESTION,
    CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE,
    AlgorithmType,
    build_feedback_marker,
    canonical_marker_hash,
    decision_types,
)
from app.services.learning_service._algorithm_registry import (
    get as get_algorithm_type,
)
from app.services.learning_service._algorithm_registry import (
    is_registered as is_algorithm_type_registered,
)
from app.services.learning_service._budget_quantile import (
    ALGORITHM_VERSION as BUDGET_QUANTILE_VERSION,
)
from app.services.learning_service._budget_quantile import (
    BudgetQuantileSuggestion,
    compute_budget_quantile_suggestion,
)
from app.services.learning_service._category_suggestion import (
    ALGORITHM_VERSION as CATEGORY_SUGGESTION_VERSION,
)
from app.services.learning_service._category_suggestion import (
    CategorySuggestion,
    compute_category_suggestion,
)
from app.services.learning_service._cleanup import (
    CleanupReport,
    cleanup_expired_algorithm_decisions,
    cleanup_expired_learning_events,
    cleanup_expired_learning_tables,
    cleanup_expired_ocr_facts,
)
from app.services.learning_service._duplicate_scoring import (
    ALGORITHM_VERSION as DUPLICATE_SCORING_VERSION,
)
from app.services.learning_service._duplicate_scoring import (
    DuplicateCandidateScore,
    score_duplicate_candidates,
)
from app.services.learning_service._lifecycle import (
    DECISION_STATUSES,
    TERMINAL_DECISION_STATUSES,
    TERMINAL_EXPENSE_STATUSES,
    close_active_decisions_for_subject,
    set_decision_status,
    stale_active_count,
    sweep_stale_active_decisions,
)
from app.services.learning_service._maintenance import (
    LearningMaintenanceResult,
    LearningStatusOverview,
    LearningTableSnapshot,
    get_status_overview,
    run_full_maintenance,
)
from app.services.learning_service._model_versions import (
    AlgorithmVersionStats,
    list_algorithm_versions,
    withdraw_algorithm_version,
)
from app.services.time_service import now_utc

__all__ = [
    "ALGORITHM_TYPES",
    "AlgorithmType",
    "AlgorithmVersionStats",
    "BUDGET_QUANTILE_VERSION",
    "BUDGET_SUGGESTION",
    "BudgetQuantileSuggestion",
    "CATEGORY_SUGGESTION",
    "CATEGORY_SUGGESTION_VERSION",
    "CategorySuggestion",
    "CleanupReport",
    "DECISION_STATUSES",
    "DUPLICATE_CANDIDATE",
    "DUPLICATE_SCORING_VERSION",
    "DecisionDraft",
    "DuplicateCandidateScore",
    "EventDraft",
    "LearningMaintenanceResult",
    "LearningStatusOverview",
    "LearningTableSnapshot",
    "OcrFactDraft",
    "TERMINAL_DECISION_STATUSES",
    "TERMINAL_EXPENSE_STATUSES",
    "active_decision_for_subject",
    "build_feedback_marker",
    "canonical_marker_hash",
    "cleanup_expired_algorithm_decisions",
    "cleanup_expired_learning_events",
    "cleanup_expired_learning_tables",
    "cleanup_expired_ocr_facts",
    "close_active_decisions_for_subject",
    "compute_budget_quantile_suggestion",
    "compute_category_suggestion",
    "decision_types",
    "get_algorithm_type",
    "get_status_overview",
    "is_algorithm_type_registered",
    "latest_ocr_fact_for_expense",
    "list_algorithm_versions",
    "ocr_facts_for_expense",
    "read_ocr_text",
    "read_ocr_texts",
    "record_decision",
    "record_event",
    "record_ocr_fact",
    "recent_events_for_subject",
    "run_full_maintenance",
    "score_duplicate_candidates",
    "set_decision_status",
    "stale_active_count",
    "supersede_decision",
    "sweep_stale_active_decisions",
    "withdraw_algorithm_version",
]


@dataclass(frozen=True)
class DecisionDraft:
    """Caller-friendly shape for :func:`record_decision`.

    ``subject_id`` may be ``None`` for tenant-wide suggestions (e.g.
    "your monthly budget for the whole ledger should be X"). The
    payload is the algorithm's full proposed output and is serialised
    to JSON before insertion.
    """

    tenant_id: str
    decision_type: str
    algorithm_version: str
    subject_kind: str
    payload: dict[str, Any]
    subject_id: int | None = None
    subject_public_id: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class EventDraft:
    """Caller-friendly shape for :func:`record_event`.

    ``decision_id`` is optional: a manual override that had no
    corresponding suggestion still produces an event, with
    ``event_type='manual_override'``.

    ``signal_type`` + ``signal_marker`` populate the indexed feedback-
    lookup columns. ``signal_type`` is the registry's
    ``decision_type`` (``"category_suggestion"`` / etc.).
    ``signal_marker`` is the small dict the registry builds via
    ``build_feedback_marker(...)``. Both can be omitted; write paths
    that don't fit the suggestion taxonomy (manual overrides without
    a corresponding decision) leave them ``None`` and are intentionally
    excluded from indexed feedback-dedup lookups.
    """

    tenant_id: str
    event_type: str
    subject_kind: str
    subject_id: int | None = None
    decision_id: int | None = None
    actor_account_id: int | None = None
    before_payload: dict[str, Any] | None = None
    after_payload: dict[str, Any] | None = None
    signal_type: str | None = None
    signal_marker: dict[str, Any] | None = None


def _dumps(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def record_decision(
    db: Session, draft: DecisionDraft, *, now: datetime | None = None
) -> AlgorithmDecision:
    """Insert one row into ``algorithm_decisions`` and return it.

    Caller is responsible for the commit. Returning the persisted row
    (with ``id`` populated via flush) lets the caller chain a follow-up
    :func:`record_event` in the same transaction when the suggestion is
    auto-confirmed by the user — that path is rare but supported.
    """

    algorithm_type = get_algorithm_type(draft.decision_type)
    row = AlgorithmDecision(
        tenant_id=draft.tenant_id,
        decision_type=draft.decision_type,
        algorithm_version=draft.algorithm_version,
        subject_kind=draft.subject_kind,
        subject_id=draft.subject_id,
        subject_public_id=draft.subject_public_id,
        score=draft.score,
        output_payload=json.dumps(
            draft.payload, sort_keys=True, ensure_ascii=False
        ),
        status="active",
        retention_days=algorithm_type.default_retention_days,
        created_at=now or now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def record_event(
    db: Session, draft: EventDraft, *, now: datetime | None = None
) -> LedgerLearningEvent:
    """Insert one row into ``ledger_learning_events`` and return it.

    Caller is responsible for the commit. This function does not
    mutate the related decision's ``status`` — that's
    :func:`supersede_decision`'s job — because "user rejected the
    suggestion" and "this decision is obsolete" are different signals.
    """

    if draft.decision_id is not None:
        decision = db.get(AlgorithmDecision, draft.decision_id)
        if decision is None:
            raise ValueError("learning decision does not exist")
        if decision.tenant_id != draft.tenant_id:
            raise ValueError("learning decision belongs to another tenant")
        if decision.subject_kind != draft.subject_kind:
            raise ValueError("learning event subject kind does not match decision")
        if decision.subject_id != draft.subject_id:
            raise ValueError("learning event subject id does not match decision")

    signal_hash = canonical_marker_hash(draft.signal_marker)
    row = LedgerLearningEvent(
        tenant_id=draft.tenant_id,
        decision_id=draft.decision_id,
        event_type=draft.event_type,
        actor_account_id=draft.actor_account_id,
        subject_kind=draft.subject_kind,
        subject_id=draft.subject_id,
        before_payload=_dumps(draft.before_payload),
        after_payload=_dumps(draft.after_payload),
        signal_type=draft.signal_type,
        signal_hash=signal_hash,
        signal_payload=_dumps(draft.signal_marker),
        created_at=now or now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def supersede_decision(
    db: Session,
    *,
    tenant_id: str,
    old_decision_id: int,
    new_decision_id: int,
) -> int:
    """Mark ``old_decision_id`` as superseded by ``new_decision_id``.

    Both ids must belong to the same tenant or the update is a no-op
    (cross-tenant supersede is a programming error; we silently refuse
    instead of raising so a misuse can't corrupt another tenant's data).

    Returns the number of rows updated (0 or 1).
    """

    old_decision = db.get(AlgorithmDecision, old_decision_id)
    new_decision = db.get(AlgorithmDecision, new_decision_id)
    if (
        old_decision is None
        or new_decision is None
        or old_decision.id == new_decision.id
        or old_decision.tenant_id != tenant_id
        or new_decision.tenant_id != tenant_id
        or old_decision.status != "active"
        or old_decision.decision_type != new_decision.decision_type
        or old_decision.subject_kind != new_decision.subject_kind
        or old_decision.subject_id != new_decision.subject_id
        or old_decision.subject_public_id != new_decision.subject_public_id
    ):
        return 0

    result = db.execute(
        update(AlgorithmDecision)
        .where(AlgorithmDecision.id == old_decision_id)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.status == "active")
        .values(status="superseded", superseded_by_id=new_decision_id)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def active_decision_for_subject(
    db: Session,
    *,
    tenant_id: str,
    decision_type: str,
    subject_kind: str,
    subject_id: int | None,
) -> AlgorithmDecision | None:
    """Latest ``active`` decision matching the (type, subject) coordinates."""

    stmt = (
        select(AlgorithmDecision)
        .where(AlgorithmDecision.tenant_id == tenant_id)
        .where(AlgorithmDecision.decision_type == decision_type)
        .where(AlgorithmDecision.subject_kind == subject_kind)
        .where(AlgorithmDecision.status == "active")
        .order_by(AlgorithmDecision.created_at.desc())
        .limit(1)
    )
    if subject_id is None:
        stmt = stmt.where(AlgorithmDecision.subject_id.is_(None))
    else:
        stmt = stmt.where(AlgorithmDecision.subject_id == subject_id)
    return db.scalar(stmt)


def recent_events_for_subject(
    db: Session,
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: int | None,
    event_types: Iterable[str] | None = None,
    limit: int = 50,
) -> list[LedgerLearningEvent]:
    """Latest events on (subject_kind, subject_id), newest first.

    ``event_types``, when provided, filters by event type — typical
    callers want "every reject the user has made on this merchant" or
    similar. ``limit`` defaults to 50 because anything above the
    recency horizon is usually not actionable.
    """

    stmt = (
        select(LedgerLearningEvent)
        .where(LedgerLearningEvent.tenant_id == tenant_id)
        .where(LedgerLearningEvent.subject_kind == subject_kind)
        .order_by(LedgerLearningEvent.created_at.desc())
        .limit(limit)
    )
    if subject_id is None:
        stmt = stmt.where(LedgerLearningEvent.subject_id.is_(None))
    else:
        stmt = stmt.where(LedgerLearningEvent.subject_id == subject_id)
    if event_types:
        stmt = stmt.where(LedgerLearningEvent.event_type.in_(list(event_types)))
    return list(db.scalars(stmt))


@dataclass(frozen=True)
class OcrFactDraft:
    """Caller shape for :func:`record_ocr_fact`.

    All ``parsed_*`` fields are optional — the OCR result that produced
    the row may have failed to detect amount / merchant / time, and we
    still want the ``raw_text`` snapshot so downstream learning can
    inspect the failure.
    """

    tenant_id: str
    expense_id: int
    ocr_provider: str
    ocr_model: str | None = None
    raw_text: str | None = None
    parsed_amount_cents: int | None = None
    parsed_merchant: str | None = None
    parsed_category: str | None = None
    parsed_expense_time: datetime | None = None
    parse_confidence: float | None = None


def record_ocr_fact(
    db: Session, draft: OcrFactDraft, *, now: datetime | None = None
) -> OcrFact:
    """Append one ``ocr_facts`` row capturing the extraction outcome.

    Caller is responsible for the commit. The table is append-only —
    multiple manual retries of the same expense produce multiple rows
    distinguished by ``extracted_at``.
    """

    expense = db.get(Expense, draft.expense_id)
    if expense is None:
        raise ValueError("ocr fact expense does not exist")
    if expense.tenant_id != draft.tenant_id:
        raise ValueError("ocr fact expense belongs to another tenant")

    timestamp = now or now_utc()
    row = OcrFact(
        tenant_id=draft.tenant_id,
        expense_id=draft.expense_id,
        ocr_provider=draft.ocr_provider,
        ocr_model=draft.ocr_model,
        raw_text=draft.raw_text,
        parsed_amount_cents=draft.parsed_amount_cents,
        parsed_merchant=draft.parsed_merchant,
        parsed_category=draft.parsed_category,
        parsed_expense_time=draft.parsed_expense_time,
        parse_confidence=draft.parse_confidence,
        extracted_at=timestamp,
        created_at=timestamp,
    )
    db.add(row)
    db.flush()
    return row


def ocr_facts_for_expense(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
    limit: int = 20,
) -> list[OcrFact]:
    """Return OCR facts for ``expense_id`` newest first.

    Caller can ask for more than the default 20 if they really want the
    full history (typical UI inspection shows the latest one plus a
    "show prior runs" expander).
    """

    stmt = (
        select(OcrFact)
        .where(OcrFact.tenant_id == tenant_id)
        .where(OcrFact.expense_id == expense_id)
        .order_by(OcrFact.extracted_at.desc(), OcrFact.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def latest_ocr_fact_for_expense(
    db: Session,
    *,
    tenant_id: str,
    expense_id: int,
) -> OcrFact | None:
    """Return the most recent ``ocr_facts`` row for ``expense_id``, or
    ``None`` when the expense has never been OCR'd into the new table.

    This is the canonical read API for the OCR single-source migration
    (v1.2 P0). Consumers that need just the text should call
    :func:`read_ocr_text`, which wraps this lookup. After step 4
    dropped the ``expenses.raw_text`` fallback, ``None`` here means
    "no OCR text on record" — the legacy column is no longer
    consulted by the helper, even when it still happens to be set.
    """

    return db.scalar(
        select(OcrFact)
        .where(OcrFact.tenant_id == tenant_id)
        .where(OcrFact.expense_id == expense_id)
        .order_by(OcrFact.extracted_at.desc(), OcrFact.id.desc())
        .limit(1)
    )


def read_ocr_text(
    db: Session,
    *,
    tenant_id: str,
    expense: Expense,
) -> str | None:
    """Single-source read for "the raw OCR text we recorded for this
    expense".

    The newest ``ocr_facts.raw_text`` that actually carries text is
    the canonical answer. The query intentionally **filters out empty
    rows** instead of taking the absolute latest fact and falling
    back to ``None`` when that one happens to be hollow — otherwise
    an empty OCR pass (``EmptyOcrProvider`` on systems with no OCR
    configured, a provider error that returned only confidence, …)
    would clobber the previously-recorded meaningful text just by
    appending a row. The mirror column ``expense.raw_text`` is **not**
    consulted regardless of column state.

    Returns ``None`` when no fact for this expense carries non-empty
    text. The pre-step-4 wrapper used to fall back to the legacy
    column here; that branch was dropped after the step-3 backfill
    (``bb00c453bf29``).
    """

    if expense.tenant_id != tenant_id:
        return None
    return db.scalar(
        select(OcrFact.raw_text)
        .where(OcrFact.tenant_id == tenant_id)
        .where(OcrFact.expense_id == expense.id)
        .where(OcrFact.raw_text.is_not(None))
        .where(OcrFact.raw_text != "")
        .order_by(OcrFact.extracted_at.desc(), OcrFact.id.desc())
        .limit(1)
    )


def read_ocr_texts(
    db: Session,
    *,
    tenant_id: str,
    expenses: Iterable[Expense],
) -> dict[int, str]:
    """Bulk variant of :func:`read_ocr_text` for response assembly."""

    expense_ids = [
        int(expense.id)
        for expense in expenses
        if expense.id is not None and expense.tenant_id == tenant_id
    ]
    if not expense_ids:
        return {}

    rows = db.execute(
        select(OcrFact.expense_id, OcrFact.raw_text)
        .where(OcrFact.tenant_id == tenant_id)
        .where(OcrFact.expense_id.in_(expense_ids))
        .where(OcrFact.raw_text.is_not(None))
        .where(OcrFact.raw_text != "")
        .order_by(OcrFact.expense_id, OcrFact.extracted_at.desc(), OcrFact.id.desc())
    )
    by_expense_id: dict[int, str] = {}
    for expense_id, raw_text in rows:
        expense_id_int = int(expense_id)
        if expense_id_int not in by_expense_id:
            by_expense_id[expense_id_int] = raw_text
    return by_expense_id
