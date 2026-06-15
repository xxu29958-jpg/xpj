"""ADR-0049 §6: the ``debt_repayment`` goal evaluator + lifecycle.

A debt_repayment goal tracks the clearance of an explicit set of Debts instead
of a monthly spend target. Slice 6 widens the ``goals`` table (see
``app.models.budget`` + the 20260615_0001 migration) and this module owns the
debt-only logic, keeping ``goal_service`` focused on spending_limit. The route
layer reaches the shared create/get dispatch through ``goal_service`` (the
facade) and the debt-only ops (link replace / list) directly here.

Evaluator semantics (§6), over the goal's CURRENT ``goal_version`` link set:

* any linked Debt ``voided``  -> ``not_evaluable`` (``needs_review``; the UI must
  offer a review action — replace the link set into a new version — so a voided
  Debt never silently freezes the goal, §6 / F13)
* else every linked Debt ``cleared`` -> ``achieved`` (latched once into
  ``Goal.achieved_at`` / ``achieved_version`` and sticky thereafter, so a linked
  Debt reopening later does NOT un-achieve the version)
* else -> ``in_progress``

The linked Debt set is FROZEN per goal version: replacing the links bumps
``goal_version`` and writes a fresh ``DebtGoalLink`` batch for the new version
while old-version rows are kept, so unlinking an open Debt cannot retroactively
achieve an older version (§6).

The evaluation never mutates Debt state — it reads each Debt's derived fold
status (``derive_status(debt, compute_remaining(...))``, the ADR-0049 §2 single
definition), so it is correct even if the persisted ``Debt.status`` column lags a
concurrent in-flight write.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import Debt, DebtGoalLink, Goal
from app.schemas import (
    DebtGoalIntegrityReviewRequest,
    DebtGoalLinksReplaceRequest,
    DebtGoalLinkView,
    DebtRepaymentEvaluation,
    GoalCreateRequest,
    GoalResponse,
)
from app.services.debt_service import compute_remaining, derive_status
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc

GOAL_TYPE = "debt_repayment"


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 80:
        raise AppError("invalid_request", status_code=422)
    return cleaned


def _require_at_least_one_debt() -> None:
    raise AppError(
        "invalid_request", "还债目标至少需要关联一笔欠款。", status_code=422
    )


def _resolve_linked_debts(
    db: Session, *, tenant_id: str, debt_public_ids: list[str] | None
) -> list[Debt]:
    """Resolve + dedupe ``debt_public_ids`` to tenant-scoped ``Debt`` rows.

    Order-preserving dedupe; any id not visible in this tenant raises
    ``debt_not_found`` (404, ledger-scoped existence hiding). Requiring all ids to
    resolve keeps a goal from silently tracking fewer Debts than the client named.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in debt_public_ids or []:
        pid = (raw or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            cleaned.append(pid)
    if not cleaned:
        _require_at_least_one_debt()
    rows = list(
        db.scalars(ledger_scoped_select(Debt, tenant_id).where(Debt.public_id.in_(cleaned)))
    )
    by_public = {debt.public_id: debt for debt in rows}
    for pid in cleaned:
        if pid not in by_public:
            raise AppError("debt_not_found", status_code=404)
    return [by_public[pid] for pid in cleaned]


def _require_debt_repayment_goal(db: Session, *, tenant_id: str, public_id: str) -> Goal:
    goal = db.scalar(
        ledger_scoped_select(Goal, tenant_id).where(Goal.public_id == public_id).limit(1)
    )
    if goal is None:
        raise AppError("goal_not_found", status_code=404)
    if goal.goal_type != GOAL_TYPE:
        raise AppError("invalid_request", "该目标不是还债目标。", status_code=422)
    return goal


def _current_version_debts(db: Session, goal: Goal) -> list[Debt]:
    statement = (
        select(Debt)
        .join(DebtGoalLink, DebtGoalLink.debt_id == Debt.id)
        .where(DebtGoalLink.goal_id == goal.id)
        .where(DebtGoalLink.goal_version == goal.goal_version)
        .order_by(DebtGoalLink.id.asc())
    )
    return list(db.scalars(statement))


def _evaluate_and_maybe_latch(
    db: Session, goal: Goal, *, persist: bool
) -> tuple[DebtRepaymentEvaluation, bool]:
    """Evaluate the current-version link set; latch a fresh achievement when ``persist``.

    Returns ``(evaluation, latched)``. ``latched`` is True only when this call
    stamped ``achieved_at`` / ``achieved_version`` on ``goal`` (the caller commits).
    Achievement is sticky: once ``achieved_version == goal_version`` the state stays
    ``achieved`` regardless of the Debts' current fold (a reopened/voided linked
    Debt does not un-achieve a latched version, §6).
    """
    debts = _current_version_debts(db, goal)
    link_views: list[DebtGoalLinkView] = []
    voided_public_ids: list[str] = []
    any_voided = False
    all_cleared = bool(debts)
    for debt in debts:
        remaining = compute_remaining(db, debt)
        status = derive_status(debt, remaining)
        if status == "voided":
            any_voided = True
            voided_public_ids.append(debt.public_id)
        if status != "cleared":
            all_cleared = False
        link_views.append(
            DebtGoalLinkView(
                debt_public_id=debt.public_id,
                status=status,
                direction=debt.direction,
                counterparty_type=debt.counterparty_type,
                counterparty_label=debt.counterparty_label,
                principal_amount_cents=int(debt.principal_amount_cents),
                remaining_amount_cents=remaining,
                home_currency_code=debt.home_currency_code,
            )
        )

    already_latched = goal.achieved_version == goal.goal_version
    if already_latched:
        state = "achieved"  # §6 sticky: never reverted (reopen OR debt-void)
    elif any_voided:
        state = "not_evaluable"
    elif all_cleared:
        state = "achieved"
    else:
        state = "in_progress"

    latched = False
    if persist and state == "achieved" and not already_latched:
        goal.achieved_at = now_utc()
        goal.achieved_version = goal.goal_version
        latched = True

    # §6/F13 integrity review: a debt-VOIDED linked Debt (fold status ``voided``,
    # captured by ``any_voided``) is an unresolved integrity issue that forces a
    # review — both on a not_evaluable version AND on a sticky-achieved one — UNLESS
    # an achieved version was explicitly acknowledged for THIS goal_version. A reopen
    # (status ``open``, not ``voided``) never sets ``any_voided`` so raises no review.
    integrity_acknowledged = goal.integrity_reviewed_version == goal.goal_version
    needs_review = any_voided and not (state == "achieved" and integrity_acknowledged)

    evaluation = DebtRepaymentEvaluation(
        goal_version=goal.goal_version,
        evaluation_state=state,
        needs_review=needs_review,
        achieved_at=goal.achieved_at,
        achieved_version=goal.achieved_version,
        linked_debts=link_views,
        voided_debt_public_ids=voided_public_ids,
    )
    return evaluation, latched


def _debt_goal_response(goal: Goal, evaluation: DebtRepaymentEvaluation) -> GoalResponse:
    """A debt_repayment goal's response: spend-shape fields NULL, debt block populated."""
    return GoalResponse(
        public_id=goal.public_id,
        ledger_id=goal.tenant_id,
        name=goal.name,
        goal_type=goal.goal_type,
        period=goal.period,
        month=None,
        category=None,
        target_amount_cents=None,
        spent_amount_cents=None,
        remaining_amount_cents=None,
        progress_percent=None,
        progress_state=evaluation.evaluation_state,
        status=goal.status,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        row_version=goal.row_version,
        archived_at=goal.archived_at,
        debt_repayment=evaluation,
    )


def build_debt_repayment_goal_response(
    db: Session, goal: Goal, *, persist_achievement: bool
) -> GoalResponse:
    """Evaluate + (writer paths only) persist a fresh achievement latch, then serialize.

    ``persist_achievement`` is gated to writer contexts by the caller — a viewer's
    read computes the state but never writes (the latch is a derived milestone, but
    materializing it stays a writer action). When a fresh achievement is latched the
    write is committed here (monotonic + idempotent: re-latching the same version is
    a no-op), so a later linked-Debt reopen finds the version already achieved.
    """
    evaluation, latched = _evaluate_and_maybe_latch(db, goal, persist=persist_achievement)
    if latched:
        db.commit()
    return _debt_goal_response(goal, evaluation)


def create_debt_repayment_goal(
    db: Session, *, tenant_id: str, payload: GoalCreateRequest
) -> GoalResponse:
    """Create a debt_repayment goal at ``goal_version=1`` linking the named Debts."""
    if (
        payload.month is not None
        or payload.category is not None
        or payload.target_amount_cents is not None
    ):
        raise AppError(
            "invalid_request",
            "还债目标不接受月份 / 分类 / 目标金额。",
            status_code=422,
        )
    if not payload.debt_public_ids:
        _require_at_least_one_debt()
    debts = _resolve_linked_debts(
        db, tenant_id=tenant_id, debt_public_ids=payload.debt_public_ids
    )
    now = now_utc()
    goal = Goal(
        tenant_id=tenant_id,
        name=_clean_name(payload.name),
        goal_type=GOAL_TYPE,
        period="monthly",
        month=None,
        category=None,
        target_amount_cents=None,
        status="active",
        goal_version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.flush()
    for debt in debts:
        db.add(
            DebtGoalLink(
                goal_id=goal.id, goal_version=1, debt_id=debt.id, created_at=now
            )
        )
    db.commit()
    db.refresh(goal)
    # persist_achievement=True: linking already-cleared Debts achieves immediately.
    return build_debt_repayment_goal_response(db, goal, persist_achievement=True)


def replace_debt_repayment_goal_links(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalLinksReplaceRequest,
    commit: bool = True,
) -> None:
    """Replace the linked Debt set → a NEW goal version (ADR-0049 §6).

    OCC-gated by ``expected_row_version`` (the audit's mutate-token lane sees the
    token in the request schema). The claim bumps ``Goal.row_version`` and sets
    ``goal_version = goal_version + 1``; a fresh ``DebtGoalLink`` batch is written
    for the new version while old-version rows stay (versions are frozen). Old
    achievement latches are NOT reset — ``achieved_version`` still points at
    whatever version achieved, so the new (unachieved) version re-evaluates fresh.

    ``commit=False`` lets the route commit the OCC claim together with the
    ADR-0042 idempotency-key success record in one transaction (mirrors
    ``goal_service.update_goal``); the response is built by the route after commit.
    """
    goal = _require_debt_repayment_goal(db, tenant_id=tenant_id, public_id=public_id)
    if goal.status == "archived":
        raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)
    debts = _resolve_linked_debts(
        db, tenant_id=tenant_id, debt_public_ids=payload.debt_public_ids
    )
    now = now_utc()
    new_version = goal.goal_version + 1
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"goal_version": new_version, "updated_at": now},
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_debt_repayment_goal(db, tenant_id=tenant_id, public_id=public_id)
        if current.status != "active":
            raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)
        raise AppError("state_conflict", status_code=409)
    for debt in debts:
        db.add(
            DebtGoalLink(
                goal_id=goal.id, goal_version=new_version, debt_id=debt.id, created_at=now
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()


def acknowledge_integrity_review(
    db: Session,
    *,
    tenant_id: str,
    public_id: str,
    payload: DebtGoalIntegrityReviewRequest,
    commit: bool = True,
) -> None:
    """ADR-0049 §6/F13: acknowledge ("keep for audit") an achieved version's debt-void.

    Records the acknowledgement against the CURRENT ``goal_version`` so the integrity
    ``needs_review`` flag clears for that version. Only valid for an ALREADY-achieved
    version that carries a debt-voided linked Debt — a not-yet-achieved version's
    voided Debt is resolved by replacing links (the other exit). OCC-gated like the
    link-replace route; ``commit=False`` lets the route commit it with the idempotency
    success record.
    """
    goal = _require_debt_repayment_goal(db, tenant_id=tenant_id, public_id=public_id)
    if goal.status == "archived":
        raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)
    evaluation, _ = _evaluate_and_maybe_latch(db, goal, persist=False)
    if evaluation.evaluation_state != "achieved" or not evaluation.voided_debt_public_ids:
        raise AppError(
            "invalid_request",
            "没有待确认的债务作废复核（目标须已达成且有被作废的关联欠款）。",
            status_code=422,
        )
    if goal.integrity_reviewed_version == goal.goal_version:
        return  # already acknowledged for this version — idempotent no-op
    now = now_utc()
    rowcount = claim_row_with_token(
        db,
        Goal,
        pk_id=goal.id,
        tenant_id=tenant_id,
        expected_row_version=payload.expected_row_version,
        set_values={"integrity_reviewed_version": goal.goal_version, "updated_at": now},
        extra_where=(Goal.status == "active",),
        synchronize_session=False,
    )
    if rowcount != 1:
        db.rollback()
        current = _require_debt_repayment_goal(db, tenant_id=tenant_id, public_id=public_id)
        if current.status != "active":
            raise AppError("invalid_request", "目标已归档，不能继续修改。", status_code=409)
        raise AppError("state_conflict", status_code=409)
    if commit:
        db.commit()
    else:
        db.flush()


def list_debt_repayment_goals(
    db: Session, *, tenant_id: str, include_archived: bool = False
) -> list[GoalResponse]:
    """List a tenant's debt_repayment goals (read-only — never latches achievement)."""
    statement = ledger_scoped_select(Goal, tenant_id).where(Goal.goal_type == GOAL_TYPE)
    if not include_archived:
        statement = statement.where(Goal.status != "archived")
    statement = statement.order_by(
        Goal.status.asc(), Goal.created_at.asc(), Goal.id.asc()
    )
    goals = list(db.scalars(statement))
    return [
        build_debt_repayment_goal_response(db, goal, persist_achievement=False)
        for goal in goals
    ]
