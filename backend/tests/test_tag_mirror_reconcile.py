"""ADR-0043 slice A: one-time expense_tags ↔ tags-string mirror reconcile.

``backfill_expense_tags`` only seeds links when a ledger has *none*; it can't
fix partial drift. ``reconcile_expense_tag_mirror`` is the independent pass that
rebuilds relation rows from the (source-of-truth) denormalised string and bumps
``row_version`` on every row it repairs (契约 1).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseTag
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.tag_service import reconcile_expense_tag_mirror
from app.services.time_service import now_utc


def _manual_with_tag(
    client: TestClient, headers: dict[str, str], tags: str, *, merchant: str = "镜像"
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": 1000,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-02T00:00:00Z",
            "tags": tags,
        },
    )
    assert response.status_code == 200
    return response.json()


def _claim_with_version(expense_id: int, expected_row_version: int) -> int:
    """Return rowcount of an OCC-guarded claim carrying ``expected_row_version``."""
    with SessionLocal() as db:
        rowcount = claim_row_with_token(
            db,
            Expense,
            pk_id=expense_id,
            tenant_id="owner",
            expected_row_version=expected_row_version,
            set_values={"updated_at": now_utc()},
            synchronize_session=False,
        )
        db.rollback()
    return rowcount


def _only_expense_id(tenant_id: str = "owner") -> int:
    with SessionLocal() as db:
        return db.scalars(select(Expense).where(Expense.tenant_id == tenant_id)).one().id


def _links(expense_id: int) -> list[ExpenseTag]:
    with SessionLocal() as db:
        return list(db.scalars(select(ExpenseTag).where(ExpenseTag.expense_id == expense_id)))


def _row_version(expense_id: int) -> int:
    with SessionLocal() as db:
        return db.get(Expense, expense_id).row_version


def test_reconcile_relinks_missing_relation_row_and_bumps(client: TestClient, *, identity) -> None:
    _manual_with_tag(client, identity.app_headers, "食物")
    expense_id = _only_expense_id()
    before = _row_version(expense_id)

    # Corrupt: drop the relation row so the string "食物" has no backing link.
    with SessionLocal() as db:
        for link in db.scalars(select(ExpenseTag).where(ExpenseTag.expense_id == expense_id)):
            db.delete(link)
        db.commit()
    assert _links(expense_id) == []

    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 1

    assert len(_links(expense_id)) == 1
    assert _row_version(expense_id) == before + 1


def test_reconcile_removes_orphan_link_when_string_cleared(client: TestClient, *, identity) -> None:
    _manual_with_tag(client, identity.app_headers, "食物")
    expense_id = _only_expense_id()
    before = _row_version(expense_id)

    # Corrupt: clear the denormalised string but leave the relation row.
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        expense.tags = None
        db.commit()

    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 1

    assert _links(expense_id) == []
    assert _row_version(expense_id) == before + 1


def test_reconcile_is_noop_and_idempotent_when_consistent(client: TestClient, *, identity) -> None:
    _manual_with_tag(client, identity.app_headers, "食物")
    expense_id = _only_expense_id()
    before = _row_version(expense_id)

    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 0
    # Second pass after a real repair must also settle to a no-op.
    with SessionLocal() as db:
        for link in db.scalars(select(ExpenseTag).where(ExpenseTag.expense_id == expense_id)):
            db.delete(link)
        db.commit()
    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 1
    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 0

    # exactly one bump from the single repair, none from the two no-op passes.
    assert _row_version(expense_id) == before + 1


def test_reconcile_bump_is_occ_effective(client: TestClient, *, identity) -> None:
    """Contract 1: the bump must actually invalidate a stale OCC token — a PATCH
    carrying the pre-reconcile row_version would 409, not silently revert."""
    _manual_with_tag(client, identity.app_headers, "食物")
    expense_id = _only_expense_id()
    before = _row_version(expense_id)
    # Pre-reconcile token claims fine; establishes the baseline.
    assert _claim_with_version(expense_id, before) == 1

    with SessionLocal() as db:
        for link in db.scalars(select(ExpenseTag).where(ExpenseTag.expense_id == expense_id)):
            db.delete(link)
        db.commit()
    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 1

    # The pre-reconcile row_version no longer claims (a stale PATCH → 409);
    # the current bumped version does.
    assert _claim_with_version(expense_id, before) == 0
    assert _claim_with_version(expense_id, _row_version(expense_id)) == 1


def test_reconcile_leaves_unrelated_expense_unbumped(client: TestClient, *, identity) -> None:
    """ADR matrix '无关账单不 bump': only the drifted row is repaired/bumped."""
    _manual_with_tag(client, identity.app_headers, "食物", merchant="漂移")
    _manual_with_tag(client, identity.app_headers, "差旅", merchant="干净")
    with SessionLocal() as db:
        by_merchant = {
            expense.merchant: expense.id
            for expense in db.scalars(select(Expense).where(Expense.tenant_id == "owner"))
        }
        drifted_id, clean_id = by_merchant["漂移"], by_merchant["干净"]
        drifted_before = db.get(Expense, drifted_id).row_version
        clean_before = db.get(Expense, clean_id).row_version
        # Corrupt only the "漂移" expense.
        for link in db.scalars(select(ExpenseTag).where(ExpenseTag.expense_id == drifted_id)):
            db.delete(link)
        db.commit()

    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner") == 1

    assert _row_version(drifted_id) == drifted_before + 1
    assert _row_version(clean_id) == clean_before  # untouched
    assert len(_links(clean_id)) == 1


def test_reconcile_repairs_across_multiple_batches(client: TestClient, *, identity) -> None:
    """ADR '分批': keyset-paged reconcile repairs every drifted row across batch
    boundaries, each bumped exactly once, with a correct total count."""
    for i in range(3):
        _manual_with_tag(client, identity.app_headers, f"标签{i}", merchant=f"商家{i}")
    with SessionLocal() as db:
        before = {
            expense.id: expense.row_version
            for expense in db.scalars(select(Expense).where(Expense.tenant_id == "owner"))
        }
        # Drop every link → all three drift.
        for link in db.scalars(select(ExpenseTag).where(ExpenseTag.tenant_id == "owner")):
            db.delete(link)
        db.commit()
    assert len(before) == 3

    with SessionLocal() as db:
        assert reconcile_expense_tag_mirror(db, "owner", batch_size=2) == 3

    for expense_id, version in before.items():
        assert _row_version(expense_id) == version + 1  # each bumped exactly once
        assert len(_links(expense_id)) == 1  # link rebuilt
