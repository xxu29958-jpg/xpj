"""Regression consumers for the confirmed-at publication boundary.

Historical rows may be currently rejected, but category startup normalization
and tag identity commands still mutate their published financial projection.
Both must go through the existing revision Owner before a later undo can make
that projection current again.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, ExpenseRevision
from app.services.category_service import normalize_existing_expense_categories
from app.services.expense_revision_service import record_confirmation_revision
from app.services.time_service import now_utc
from tests._infra.tag_helpers import manual_expense, tag_index


def test_startup_category_normalization_revises_a_historically_published_rejected_fact(
    client: TestClient,
) -> None:
    del client
    now = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1200,
            merchant="历史拒绝分类",
            category="吃饭",
            status="confirmed",
            expense_time=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            confirmed_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.flush()
        record_confirmation_revision(
            db,
            expense,
            actor_account_id=None,
            actor_device_id=None,
        )
        expense.status = "rejected"
        expense.rejected_at = now
        db.commit()
        expense_id = expense.id
        before_row_version = expense.row_version
        before_fact_revision = expense.fact_revision

    with SessionLocal() as db:
        normalize_existing_expense_categories(db, "owner")

    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        revisions = list(
            db.scalars(
                select(ExpenseRevision)
                .where(ExpenseRevision.expense_id == expense_id)
                .order_by(ExpenseRevision.revision_number.asc())
            )
        )
        assert expense is not None
        assert expense.status == "rejected"
        assert expense.category == "餐饮"
        assert expense.row_version == before_row_version + 1
        assert expense.fact_revision == before_fact_revision + 1
        assert len(revisions) == 2
        assert revisions[-1].before_snapshot["category"] == "吃饭"
        assert revisions[-1].after_snapshot["category"] == "餐饮"


def test_tag_rename_revises_a_historically_published_rejected_fact_before_undo(
    client: TestClient, *, identity
) -> None:
    headers = identity.app_headers
    created = manual_expense(client, headers, tags="食物", merchant="历史拒绝标签")
    expense_id = int(created["id"])
    before_fact_revision = int(created["fact_revision"])
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        assert expense is not None
        expense.status = "rejected"
        expense.rejected_at = now_utc()
        db.commit()

    tag = tag_index(client, headers)["食物"]
    renamed = client.post(
        f"/api/tags/{tag['public_id']}/rename",
        headers=headers,
        json={"expected_row_version": tag["row_version"], "name": "餐饮"},
    )
    assert renamed.status_code == 200, renamed.text

    current = client.get(f"/api/expenses/{expense_id}", headers=headers).json()
    assert current["status"] == "rejected"
    assert current["tags"] == "餐饮"
    assert current["fact_revision"] == before_fact_revision + 1
    history = client.get(f"/api/expenses/{expense_id}/revisions", headers=headers).json()
    assert history["items"][0]["before"]["tags"] == "食物"
    assert history["items"][0]["after"]["tags"] == "餐饮"

    restored = client.post(
        f"/api/expenses/{expense_id}/undo",
        headers=headers,
        json={"expected_row_version": current["row_version"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "confirmed"
    assert restored.json()["tags"] == "餐饮"
    assert restored.json()["fact_revision"] == before_fact_revision + 1
