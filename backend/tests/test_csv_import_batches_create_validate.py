from __future__ import annotations

import csv as csv_module
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, LedgerMember
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
    list_csv_import_rows,
)


def _csv_bytes(row_count: int) -> BytesIO:
    lines = ["amount_yuan,merchant,category,note"]
    lines.extend(f"{index}.00,Merchant {index},餐饮,note {index}" for index in range(1, row_count + 1))
    return BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_csv_import_batch_handles_more_than_legacy_preview_limit_with_paged_apply(client: TestClient) -> None:
    del client
    with SessionLocal() as db:
        batch = create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="large.csv",
            file_obj=_csv_bytes(10_000),
        )
        assert batch.total_rows == 10_000
        assert batch.valid_rows == 10_000
        assert batch.error_rows == 0

        second_page = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=2,
            page_size=500,
        )
        assert second_page.total == 10_000
        assert len(second_page.items) == 500
        assert second_page.items[0].line_number == 502

        last_page = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=20,
            page_size=500,
        )
        assert len(last_page.items) == 500
        assert last_page.items[0].line_number == 9502

        inserted_count = 0
        for expected_remaining in range(9000, -1, -1000):
            applied = apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=batch.public_id,
                batch_size=1000,
            )
            inserted_count += applied.inserted_count
            assert applied.inserted_count == 1000
            assert applied.remaining_valid_rows == expected_remaining
        assert inserted_count == 10_000
        assert applied.batch.status == "applied"

        with pytest.raises(AppError) as terminal_apply:
            apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=batch.public_id,
                batch_size=700,
            )
        assert terminal_apply.value.status_code == 409

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 10_000


def test_csv_import_batch_converts_csv_reader_errors_to_invalid_request(client: TestClient) -> None:
    del client
    old_limit = csv_module.field_size_limit()
    csv_module.field_size_limit(8)
    try:
        with SessionLocal() as db, pytest.raises(AppError) as exc_info:
            create_csv_import_batch(
                db,
                tenant_id="owner",
                file_name="bad.csv",
                file_obj=BytesIO(b"amount_yuan,merchant\n1.00,VeryLongMerchant\n"),
            )
    finally:
        csv_module.field_size_limit(old_limit)
    assert exc_info.value.error == "invalid_request"


def test_csv_import_rejects_conflicting_amount_yuan_and_cents(client: TestClient, *, identity) -> None:
    csv = "amount_yuan,amount_cents,merchant\n2.00,100,Conflicting Cafe\n"
    created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("conflict.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["valid_rows"] == 0
    assert batch["error_rows"] == 1

    rows = client.get(
        f"/api/imports/csv/{batch['public_id']}/rows?status=error",
        headers=identity.app_headers,
    )
    assert rows.status_code == 200, rows.json()
    assert rows.json()["items"][0]["status"] == "error"
    assert "amount_yuan" in rows.json()["items"][0]["error_message"]
    assert "amount_cents" in rows.json()["items"][0]["error_message"]


def test_csv_import_foreign_amount_cents_is_original_minor_not_home_amount(client: TestClient, *, identity) -> None:
    rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7.0000",
            "source": "manual",
        },
    )
    assert rate.status_code == 200, rate.json()
    csv = "\n".join(
        [
            "amount_cents,original_currency_code,exchange_rate_to_cny,exchange_rate_date,merchant,category",
            "12345,USD,7.0000,2026-05-04,Foreign Cafe,餐饮",
            "",
        ]
    )
    created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["valid_rows"] == 1
    assert batch["error_rows"] == 0

    rows = client.get(
        f"/api/imports/csv/{batch['public_id']}/rows",
        headers=identity.app_headers,
    )
    assert rows.status_code == 200, rows.json()
    row = rows.json()["items"][0]
    assert row["amount_cents"] is None
    assert row["original_currency_code"] == "USD"
    assert row["original_amount_minor"] == 12345

    applied = client.post(
        f"/api/imports/csv/{batch['public_id']}/apply",
        headers=identity.app_headers,
        json={"batch_size": 10},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["inserted_count"] == 1

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    target = next(item for item in pending.json() if item["merchant"] == "Foreign Cafe")
    assert target["original_currency_code"] == "USD"
    assert target["original_amount_minor"] == 12345
    assert target["exchange_rate_date"] == "2026-05-04"
    assert target["amount_cents"] == 86415
