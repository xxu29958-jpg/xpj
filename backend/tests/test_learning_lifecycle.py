"""v1.2 ops — active-decision lifecycle closing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense
from app.services.expense_service._update import (
    confirm_expense,
    reject_expense,
)
from app.services.learning_service import (
    DecisionDraft,
    close_active_decisions_for_subject,
    record_decision,
    sweep_stale_active_decisions,
)


def _seed_pending_expense(merchant: str = "m") -> int:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1000,
            merchant=merchant,
            category="餐饮",
            source="pytest",
            raw_text="",
            status="pending",
            expense_time=now - timedelta(hours=1),
        )
        db.add(expense)
        db.commit()
        return expense.id


def _seed_active_decision(expense_id: int, *, tenant_id: str = "owner") -> int:
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id=tenant_id,
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=expense_id,
                payload={"category": "餐饮"},
            ),
        )
        db.commit()
        return row.id


def test_close_for_subject_flips_active_rows(*, identity) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)
    with SessionLocal() as db:
        rowcount = close_active_decisions_for_subject(
            db,
            tenant_id="owner",
            subject_kind="expense",
            subject_id=expense_id,
        )
        db.commit()
        assert rowcount == 1
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision is not None
        assert decision.status == "withdrawn"


def test_close_is_tenant_scoped(*, identity) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id, tenant_id="owner")
    with SessionLocal() as db:
        # Trying to close from another tenant must not touch the row.
        rowcount = close_active_decisions_for_subject(
            db,
            tenant_id="tester_1",
            subject_kind="expense",
            subject_id=expense_id,
        )
        db.commit()
        assert rowcount == 0
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "active"


def test_confirm_expense_closes_active_decisions(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)

    with SessionLocal() as db:
        confirm_expense(db, expense_id, tenant_id="owner")
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "withdrawn"


def test_reject_expense_closes_active_decisions(
    client: TestClient, *, identity
) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)

    with SessionLocal() as db:
        reject_expense(db, expense_id, tenant_id="owner")
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "withdrawn"


def test_sweep_closes_decisions_whose_expense_is_confirmed(*, identity) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)
    # Directly flip the expense status without going through
    # confirm_expense (simulating a path that bypassed the explicit
    # close).
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        expense.status = "confirmed"
        expense.confirmed_at = datetime.now(UTC)
        db.commit()

        swept = sweep_stale_active_decisions(db, tenant_id="owner")
        db.commit()
        assert swept == 1
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "withdrawn"


def test_sweep_closes_decisions_whose_expense_was_deleted(*, identity) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        db.delete(expense)
        db.commit()

        swept = sweep_stale_active_decisions(db, tenant_id="owner")
        db.commit()
        assert swept == 1
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "withdrawn"


def test_sweep_leaves_decisions_on_pending_expenses_alone(*, identity) -> None:
    expense_id = _seed_pending_expense()
    decision_id = _seed_active_decision(expense_id)
    with SessionLocal() as db:
        swept = sweep_stale_active_decisions(db, tenant_id="owner")
        db.commit()
        assert swept == 0
        decision = db.get(AlgorithmDecision, decision_id)
        assert decision.status == "active"
