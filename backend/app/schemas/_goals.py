"""Goals CRUD payloads.

Slice 6 (ADR-0049 §6) widens these from spending-limit-only to also carry
``debt_repayment`` goals. A debt_repayment goal has no monthly spend target — it
links explicit Debt ids and is "achieved" once all linked Debts are cleared — so
the spending-shape numeric fields (``month`` / ``target_amount_cents`` /
``spent_amount_cents`` / ``remaining_amount_cents`` / ``progress_percent``) become
optional (``None`` for a debt_repayment goal) and a nested ``debt_repayment``
evaluation block carries the goal-version + linked-Debt state instead. The
existing month-scoped ``GET /api/goals`` and ``/web/goals`` only ever surface
spending_limit goals (a debt goal has ``month = None`` and is excluded by the
month filter), so those numeric fields stay populated on every response a
spending-only client sees.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "DebtGoalLinkView",
    "DebtGoalLinksReplaceRequest",
    "DebtGoalTargetDateRequest",
    "DebtRepaymentEvaluation",
    "GoalCreateRequest",
    "GoalListResponse",
    "GoalResponse",
    "GoalUpdateRequest",
]


class GoalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    goal_type: str = "spending_limit"
    period: str = "monthly"
    # spending_limit shape: month + target are REQUIRED for spending_limit and
    # rejected for debt_repayment — the service enforces the per-type rule (the
    # schema can't, since one route serves both goal types).
    month: str | None = Field(default=None, min_length=7, max_length=7)
    category: str | None = Field(default=None, max_length=64)
    target_amount_cents: int | None = Field(default=None, gt=0)
    # debt_repayment shape: the Debt ids whose clearance the goal tracks. Required
    # (non-empty) for debt_repayment and rejected for spending_limit (service-enforced).
    debt_public_ids: list[str] | None = Field(default=None)
    # ADR-0049 §7.0 / 8e-6c: optional payoff deadline for a debt_repayment goal (drives the
    # three-state). Rejected for spending_limit (service-enforced). NULL = no deadline.
    target_date: date | None = None


class GoalUpdateRequest(BaseModel):
    """ADR-0038 PR-2j: ``PATCH /api/goals/{public_id}`` body (spending_limit edits).

    ``expected_row_version`` is the client's last-seen optimistic-
    concurrency token. Service issues atomic ``UPDATE WHERE id,
    tenant_id, updated_at = expected`` and returns 409 ``state_conflict``
    on stale snapshot. Debt_repayment goals do NOT change month/category/
    target through this body — their linked Debt set changes via
    ``POST /api/goals/{public_id}/debt-links`` (a new goal version).
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int
    name: str | None = Field(default=None, min_length=1, max_length=80)
    month: str | None = Field(default=None, min_length=7, max_length=7)
    category: str | None = Field(default=None, max_length=64)
    target_amount_cents: int | None = Field(default=None, gt=0)


class DebtGoalLinksReplaceRequest(BaseModel):
    """ADR-0049 §6: replace a debt_repayment goal's linked Debt set (new version).

    Carries ``expected_row_version`` so the audit's mutate-token coverage lane
    classifies the route as a fold-changing OCC carrier (the link change bumps the
    goal's ``row_version`` + ``goal_version``). ``debt_public_ids`` is the FULL new
    set (replace semantics, not add/remove deltas) and must be non-empty — a debt
    goal always tracks at least one Debt.
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int
    debt_public_ids: list[str] = Field(min_length=1)


class DebtGoalTargetDateRequest(BaseModel):
    """ADR-0049 §7.0 / 8e-6c: set or clear a debt_repayment goal's payoff deadline.

    OCC-gated by ``expected_row_version`` (auto-detected as a mutate-token carrier). The
    setter bumps ``row_version`` only — NOT ``goal_version`` — because the deadline is goal-
    level config orthogonal to the frozen linked-Debt set; bumping ``goal_version`` would
    create an empty version and silently un-achieve the goal.

    ``target_date`` is OPTIONAL (defaults to clear): this is a SETTER, so an *omitted* field
    unambiguously means "clear the deadline" (there is no partial-update ambiguity). Requiring
    it present would make the clear case unsendable from the Android Moshi client, which omits
    null fields — present-with-value sets the deadline; absent/null clears it.
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int
    target_date: date | None = None


class DebtGoalIntegrityReviewRequest(BaseModel):
    """ADR-0049 §6/F13: acknowledge ("keep for audit") an achieved goal version
    whose linked set carries a debt-voided Debt.

    OCC-gated by ``expected_row_version`` (auto-detected as a mutate-token carrier).
    Records the acknowledgement against the goal's CURRENT version, clearing the
    integrity ``needs_review`` flag for that version. The other exit — removing the
    voided Debt — goes through the link-replace route (a new version), not here.
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


class DebtGoalLinkView(BaseModel):
    """One linked Debt's shell for a debt_repayment goal's evaluation block.

    The Debt is in the goal's own ledger (the service rejects cross-tenant links),
    so this is the owner's own obligation shell — no cross-account redaction needed.
    """

    debt_public_id: str
    status: str  # open / cleared / voided (derived fold, ADR-0049 §2)
    direction: str
    counterparty_type: str
    counterparty_label: str | None = None
    principal_amount_cents: int
    remaining_amount_cents: int
    home_currency_code: str


class DebtRepaymentEvaluation(BaseModel):
    """ADR-0049 §6 debt_repayment evaluation for the goal's CURRENT version.

    ``evaluation_state``: ``in_progress`` / ``achieved`` / ``not_evaluable``.
    ``achieved`` is latched per version and sticky — a later reopen (fold status
    back to ``open``) does NOT revert it and raises no review.

    ``needs_review`` (§6/F13) is true when a linked Debt is *debt-voided* (status
    ``voided``) and that void is unresolved: a NOT-yet-achieved version is
    ``not_evaluable`` + ``needs_review``; an already-achieved version stays
    ``achieved`` + ``needs_review`` (the integrity-review case). Both exits go
    through version machinery — replace the link set (→ new version) to remove the
    voided Debt, or acknowledge ("keep for audit") to clear the flag for the
    current version. A reopen (no ``voided`` Debt) never sets ``needs_review``.
    """

    goal_version: int
    evaluation_state: str
    needs_review: bool
    achieved_at: datetime | None = None
    achieved_version: int | None = None
    linked_debts: list[DebtGoalLinkView]
    voided_debt_public_ids: list[str]
    # ADR-0049 §7.0 / 8e-6b external-debt payoff projection — pure-external plans ONLY
    # (None for member / mixed plans, server-gated per §4, and None when the observed
    # data is too thin / mixed-currency / shows no paydown). ``tracking_days`` is the
    # honest observation window the projection used (for a "按最近 N 天" caption);
    # ``projected_payoff_date`` is the calendar day (accounting-tz) the balance is
    # projected to reach zero at the observed pace. Both are populated together or both None.
    tracking_days: int | None = None
    projected_payoff_date: date | None = None
    # ADR-0049 §7.0 / 8e-6c three-state — ``target_date`` echoes the goal's payoff deadline
    # (None when unset / non-external); ``three_state`` ∈ {on_track, ahead, at_risk} is the
    # projected-payoff month vs the deadline month, populated ONLY when BOTH a deadline and a
    # projection exist (else None — never editorialise on missing data, §7.0 R4 / de-shame).
    target_date: date | None = None
    three_state: str | None = None
    # ADR-0049 §7.0 / 8e-6d suppress-on-stale floor (杠杆④): set ONLY when a positive-velocity
    # projection was suppressed because the most recent fold-changing fact is older than the
    # freshness threshold (so ``projected_payoff_date`` is None here). Carries the whole-days
    # since the last activity so the UI shows "已 N 天没更新，估算可能已过期" (warn, not a date)
    # rather than a fabricated payoff date. None in every other shape (fresh / thin / non-external).
    days_since_last_activity: int | None = None

    @field_serializer("achieved_at")
    def serialize_evaluation_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class GoalResponse(BaseModel):
    public_id: str
    ledger_id: str
    name: str
    goal_type: str
    period: str
    # None for debt_repayment goals (ADR-0049 §6); always set for spending_limit.
    month: str | None = None
    category: str | None = None
    target_amount_cents: int | None = None
    spent_amount_cents: int | None = None
    remaining_amount_cents: int | None = None
    progress_percent: int | None = None
    # spending_limit: not_started/on_track/near_limit/over_limit/archived.
    # debt_repayment: mirrors ``debt_repayment.evaluation_state`` (always populated).
    progress_state: str
    status: str
    created_at: datetime
    updated_at: datetime
    row_version: int
    archived_at: datetime | None = None
    # Populated only for debt_repayment goals.
    debt_repayment: DebtRepaymentEvaluation | None = None

    @field_serializer("created_at", "updated_at", "archived_at")
    def serialize_goal_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
