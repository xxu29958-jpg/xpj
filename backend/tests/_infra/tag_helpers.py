"""Shared helpers for the ADR-0043 tag management test files.

Extracted so test_tag_management.py and test_tag_undo.py share one set of
expense/tag setup + inspection primitives without duplication (and stay under
the 500-LOC file gate).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseTag, LedgerMember, Tag
from app.services.optimistic_concurrency import claim_row_with_token
from app.services.time_service import now_utc


def manual_expense(
    client: TestClient,
    headers: dict[str, str],
    *,
    tags: str,
    merchant: str = "商家",
    expense_time: str = "2026-05-02T00:00:00Z",
) -> dict:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": 1000,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": expense_time,
            "tags": tags,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def tag_index(client: TestClient, headers: dict[str, str]) -> dict[str, dict]:
    """GET /api/tags as {name: item}."""
    response = client.get("/api/tags", headers=headers)
    assert response.status_code == 200, response.text
    return {item["name"]: item for item in response.json()["items"]}


def expense_row(merchant: str, tenant_id: str = "owner") -> tuple[int, int, str | None]:
    """(id, row_version, tags) of the single expense with this merchant."""
    with SessionLocal() as db:
        e = db.scalars(
            select(Expense).where(Expense.tenant_id == tenant_id).where(Expense.merchant == merchant)
        ).one()
        return e.id, e.row_version, e.tags


def tag_links(expense_id: int, tenant_id: str = "owner") -> list[str]:
    """Sorted live tag names linked to the expense (via expense_tags)."""
    with SessionLocal() as db:
        names = db.scalars(
            select(Tag.name)
            .join(ExpenseTag, ExpenseTag.tag_id == Tag.id)
            .where(ExpenseTag.expense_id == expense_id)
            .where(ExpenseTag.tenant_id == tenant_id)
            .where(Tag.deleted_at.is_(None))
        ).all()
    return sorted(str(n) for n in names)


def occ_claim_blocked(expense_id: int, version: int, tenant_id: str = "owner") -> bool:
    """True if an OCC claim at ``version`` is rejected — the row moved past it
    (i.e. a stale PATCH carrying ``version`` would 409)."""
    with SessionLocal() as db:
        rc = claim_row_with_token(
            db,
            Expense,
            pk_id=expense_id,
            tenant_id=tenant_id,
            expected_row_version=version,
            set_values={"updated_at": now_utc()},
            synchronize_session=False,
        )
        db.rollback()
    return rc == 0


def demote_owner_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()
