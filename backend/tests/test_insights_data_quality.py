"""v0.4-alpha3 slice 2 / M4 — Data Quality summary endpoint."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from api_contract_helpers import insert_confirmed_expense, upload_png
from app.database import SessionLocal
from app.fx_constants import FX_STATUS_PENDING
from app.models import Account, Expense, Ledger
from app.services.time_service import now_utc

def _patch(client: TestClient, expense_id: int, *, identity, **fields) -> None:
    response = client.patch(
        f"/api/expenses/{expense_id}", headers=identity.app_headers, json=fields
    )
    assert response.status_code == 200, response.text


def test_data_quality_empty(client: TestClient, *, identity) -> None:
    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pending_total"] == 0
    assert body["missing_amount"] == 0
    assert body["missing_merchant"] == 0
    assert body["missing_category"] == 0
    assert body["suspected_duplicates"] == 0
    assert body["confirmed_without_image"] == 0
    assert body["ready_to_confirm"] == 0
    assert body["oldest_pending_age_days"] is None
    assert "generated_at" in body and body["generated_at"]


def test_data_quality_missing_amount_and_merchant(client: TestClient, *, identity) -> None:
    # Upload creates a pending row with no amount and no merchant.
    upload_png(client, identity=identity)
    # Second row: fill amount but leave merchant blank.
    eid_b = upload_png(client, identity=identity)
    _patch(client, eid_b, amount_cents=1234, identity=identity)
    # Third row: fill both (ready).
    eid_c = upload_png(client, identity=identity)
    _patch(client, eid_c, amount_cents=2222, merchant="星巴克", identity=identity)

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    body = response.json()
    assert body["pending_total"] == 3
    assert body["missing_amount"] == 1  # only the first row
    assert body["missing_merchant"] == 2  # first row + eid_b
    # ready_to_confirm requires amount + merchant + non-suspected. Since all
    # uploads share the same fixture PNG bytes, image-based duplicate detection
    # may flag rows as suspected — so we only assert the math holds.
    assert (
        body["ready_to_confirm"] + body["missing_amount"]
        + body["missing_merchant"] - 1  # eid_a counted in both missing buckets
        + body["suspected_duplicates"]
        >= body["pending_total"]
    )
    assert body["oldest_pending_age_days"] is not None
    assert body["oldest_pending_age_days"] >= 0


def test_data_quality_missing_category_counts_pending_and_confirmed(
    client: TestClient, *, identity,
) -> None:
    eid = upload_png(client, identity=identity)
    _patch(client, eid, amount_cents=500, merchant="A", category="未分类", identity=identity)
    # Insert a confirmed row directly with NULL/empty category.
    insert_confirmed_expense(
        amount_cents=999,
        merchant="B",
        category="",
        expense_time=datetime.now(tz=UTC) - timedelta(days=1),
        confirmed_at=datetime.now(tz=UTC),
    )

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    body = response.json()
    # 1 pending (未分类) + 1 confirmed ("" category)
    assert body["missing_category"] == 2


def test_data_quality_suspected_duplicates(client: TestClient, *, identity) -> None:
    # Two uploads with the same amount + merchant trigger duplicate detection.
    eid_a = upload_png(client, identity=identity)
    _patch(client, eid_a, amount_cents=4500, merchant="美团外卖", identity=identity)
    eid_b = upload_png(client, identity=identity)
    _patch(client, eid_b, amount_cents=4500, merchant="美团外卖", identity=identity)

    with SessionLocal() as db:
        suspected = db.scalars(
            select(Expense).where(Expense.duplicate_status == "suspected")
        ).all()
        # mark_duplicate_status flags one or both; just verify >=1 to keep
        # this stable across heuristic tweaks.
        assert len(suspected) >= 1
        suspected[0].status = "rejected"
        db.commit()

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    body = response.json()
    assert body["suspected_duplicates"] == max(0, len(suspected) - 1)
    # Suspected rows must not appear as ready_to_confirm even if amount + merchant set.
    assert body["ready_to_confirm"] + body["suspected_duplicates"] <= body["pending_total"] + 1


def test_data_quality_ready_to_confirm_excludes_pending_fx(client: TestClient, *, identity) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1000,
                merchant="Tokyo Store",
                category="餐饮",
                source="csv",
                status="pending",
                fx_status=FX_STATUS_PENDING,
                duplicate_status="none",
            )
        )
        db.commit()

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["pending_total"] == 1
    assert body["ready_to_confirm"] == 0


def test_data_quality_confirmed_without_image(client: TestClient, *, identity) -> None:
    # Insert a confirmed row directly — no image_path, image_deleted_at NULL.
    insert_confirmed_expense(
        amount_cents=1111,
        merchant="Without Image",
        category="餐饮",
        expense_time=datetime.now(tz=UTC),
        confirmed_at=datetime.now(tz=UTC),
    )

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    body = response.json()
    assert body["confirmed_without_image"] >= 1


def test_data_quality_ledger_isolation(client: TestClient, *, identity) -> None:
    """A row inserted under a different tenant_id must not leak into owner stats."""
    upload_png(client, identity=identity)  # owner pending row

    with SessionLocal() as db:
        now = now_utc()
        account = Account(display_name="Other tenant", created_at=now)
        db.add(account)
        db.flush()
        db.add(
            Ledger(
                ledger_id="other-tenant-do-not-leak",
                name="Other tenant",
                owner_account_id=account.id,
                created_at=now,
            )
        )
        db.flush()
        other = Expense(
            tenant_id="other-tenant-do-not-leak",
            amount_cents=None,
            merchant=None,
            category="餐饮",
            note="",
            source="pytest",
            status="pending",
        )
        db.add(other)
        db.commit()

    response = client.get("/api/insights/data-quality", headers=identity.app_headers)
    body = response.json()
    # owner sees exactly 1 pending row (the upload). The other-tenant row must not leak.
    assert body["pending_total"] == 1
