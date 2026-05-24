"""v1.2 P2 — ledger invariant audit contract."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import Expense, ExpenseSplit
from app.services.ledger_invariant_service import audit_ledger_invariants


def _make_expense(
    *,
    tenant_id: str = "owner",
    amount_cents: int | None = 1000,
    status: str = "confirmed",
    confirmed_at: datetime | None = None,
    rejected_at: datetime | None = None,
) -> int:
    base = datetime(2026, 5, 1, tzinfo=UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id=tenant_id,
            amount_cents=amount_cents,
            merchant="x",
            category="餐饮",
            source="pytest",
            raw_text="",
            status=status,
            confirmed_at=confirmed_at if status == "confirmed" else None,
            rejected_at=rejected_at if status == "rejected" else None,
            expense_time=base,
        )
        # Allow caller to force missing timestamps for invariant tests.
        if status == "confirmed" and confirmed_at is None:
            expense.confirmed_at = None
        if status == "rejected" and rejected_at is None:
            expense.rejected_at = None
        db.add(expense)
        db.commit()
        return expense.id


def _add_split(
    *,
    tenant_id: str,
    expense_id: int,
    amount_cents: int,
    member_id: int,
    position: int,
) -> None:
    with SessionLocal() as db:
        db.add(
            ExpenseSplit(
                tenant_id=tenant_id,
                expense_id=expense_id,
                member_id=member_id,
                position=position,
                amount_cents=amount_cents,
            )
        )
        db.commit()


def _owner_member_id() -> int:
    from app.models import LedgerMember

    with SessionLocal() as db:
        row = (
            db.query(LedgerMember)
            .filter(LedgerMember.ledger_id == "owner")
            .order_by(LedgerMember.id.asc())
            .first()
        )
        assert row is not None, "identity fixture must seed owner member"
        return row.id


def test_no_findings_on_clean_ledger(*, identity) -> None:
    _make_expense(confirmed_at=datetime(2026, 5, 2, tzinfo=UTC))
    with SessionLocal() as db:
        assert audit_ledger_invariants(db, tenant_id="owner") == []


def test_split_sum_mismatch_flagged(*, identity) -> None:
    expense_id = _make_expense(
        amount_cents=1000,
        confirmed_at=datetime(2026, 5, 2, tzinfo=UTC),
    )
    member_id = _owner_member_id()
    _add_split(
        tenant_id="owner",
        expense_id=expense_id,
        member_id=member_id,
        position=0,
        amount_cents=400,
    )
    # Two splits to the SAME member would violate the unique
    # (tenant, expense, member) constraint, so we only seed one
    # split and let the sum 400 ≠ 1000 trigger the mismatch.
    with SessionLocal() as db:
        findings = audit_ledger_invariants(db, tenant_id="owner")
        assert len(findings) == 1
        assert findings[0].code == "split_sum_mismatch"
        assert findings[0].expense_id == expense_id


def test_split_balanced_passes(*, identity) -> None:
    expense_id = _make_expense(
        amount_cents=1000,
        confirmed_at=datetime(2026, 5, 2, tzinfo=UTC),
    )
    member_id = _owner_member_id()
    _add_split(
        tenant_id="owner",
        expense_id=expense_id,
        member_id=member_id,
        position=0,
        amount_cents=1000,
    )
    with SessionLocal() as db:
        assert audit_ledger_invariants(db, tenant_id="owner") == []


def test_confirmed_without_timestamp_flagged(*, identity) -> None:
    _make_expense(status="confirmed", confirmed_at=None)
    with SessionLocal() as db:
        findings = audit_ledger_invariants(db, tenant_id="owner")
        assert any(
            f.code == "status_confirmed_no_timestamp" for f in findings
        )


def test_rejected_without_timestamp_flagged(*, identity) -> None:
    _make_expense(status="rejected", rejected_at=None)
    with SessionLocal() as db:
        findings = audit_ledger_invariants(db, tenant_id="owner")
        assert any(
            f.code == "status_rejected_no_timestamp" for f in findings
        )


def test_tenant_isolation(*, identity) -> None:
    # Owner has a violation; tester_1 ledger should not see it.
    _make_expense(tenant_id="owner", status="confirmed", confirmed_at=None)
    with SessionLocal() as db:
        owner = audit_ledger_invariants(db, tenant_id="owner")
        tester = audit_ledger_invariants(db, tenant_id="tester_1")
        assert len(owner) >= 1
        assert tester == []
