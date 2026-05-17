from __future__ import annotations

from datetime import timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import CsvImportRow, Expense, LedgerMember
from app.errors import AppError
from app.services.csv_import_batch_service import (
    _claim_apply_lease,
    _claim_csv_import_rows,
    apply_csv_import_batch,
    create_csv_import_batch,
    list_csv_import_rows,
)
from app.services.time_service import now_utc
from conftest import app_headers, gray_app_headers


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

        third_apply = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            batch_size=700,
        )
        assert third_apply.inserted_count == 0
        assert third_apply.remaining_valid_rows == 0

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 10_000


def test_csv_import_apply_lease_is_atomically_claimed(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="lease.csv",
            file_obj=_csv_bytes(2),
        )
        public_id = batch.public_id

    with SessionLocal() as first_db, SessionLocal() as second_db:
        claimed = _claim_apply_lease(first_db, tenant_id="owner", public_id=public_id)
        assert claimed.status == "applying"
        assert claimed.locked_until is not None

        with pytest.raises(AppError) as exc_info:
            _claim_apply_lease(second_db, tenant_id="owner", public_id=public_id)
        assert exc_info.value.status_code == 409
        assert exc_info.value.error == "invalid_request"

    with SessionLocal() as db:
        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
        )
        assert inserted == 0


def test_csv_import_row_claim_recovers_stale_apply_after_batch_lease_expires(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="row-claim.csv",
            file_obj=_csv_bytes(2),
        )
        public_id = batch.public_id
        batch_id = batch.id
        claimed_ids = _claim_csv_import_rows(
            setup_db,
            tenant_id="owner",
            batch_id=batch_id,
            batch_size=1,
        )
        assert len(claimed_ids) == 1

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 1
        assert applied.remaining_valid_rows == 1

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 1

        rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
                .order_by(CsvImportRow.line_number.asc())
            )
        )
        assert sorted(row.status for row in rows) == ["applied", "applying"]

        with pytest.raises(AppError) as exc_info:
            apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=public_id,
                batch_size=10,
            )
        assert exc_info.value.status_code == 409

        inserted_after_retry = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted_after_retry == 1

        db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
            .where(CsvImportRow.status == "applying")
            .values(updated_at=now_utc() - timedelta(minutes=10))
        )
        db.commit()

        recovered = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert recovered.inserted_count == 1
        assert recovered.remaining_valid_rows == 0

        final_rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
            )
        )
        assert sorted(row.status for row in final_rows) == ["applied", "applied"]

        final_inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert final_inserted == 2


def test_csv_import_batch_http_flow_errors_csv_and_tenant_scope(client: TestClient) -> None:
    csv = "amount_yuan,merchant,category\nabc,Bad,餐饮\n4.50,Good,交通\n"
    created = client.post(
        "/api/imports/csv",
        headers=app_headers(),
        files={"csv_file": ("C:\\temp\\rows.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["file_name"] == "rows.csv"
    assert batch["total_rows"] == 2
    assert batch["valid_rows"] == 1
    assert batch["error_rows"] == 1
    assert batch["status"] == "parsed_with_errors"

    public_id = batch["public_id"]
    rows = client.get(
        f"/api/imports/csv/{public_id}/rows?page_size=1",
        headers=app_headers(),
    )
    assert rows.status_code == 200, rows.json()
    assert rows.json()["total"] == 2
    assert rows.json()["items"][0]["status"] == "error"

    error_rows = client.get(
        f"/api/imports/csv/{public_id}/rows?status=error",
        headers=app_headers(),
    )
    assert error_rows.status_code == 200, error_rows.json()
    assert error_rows.json()["total"] == 1
    assert "amount_yuan" in error_rows.json()["items"][0]["error_message"]

    errors_csv = client.get(f"/api/imports/csv/{public_id}/errors.csv", headers=app_headers())
    assert errors_csv.status_code == 200
    assert errors_csv.content.startswith(b"\xef\xbb\xbf")
    assert "Bad" in errors_csv.text
    assert "amount_yuan" in errors_csv.text

    gray_read = client.get(f"/api/imports/csv/{public_id}", headers=gray_app_headers())
    assert gray_read.status_code == 404
    assert gray_read.json()["error"] == "import_batch_not_found"

    applied = client.post(
        f"/api/imports/csv/{public_id}/apply",
        headers=app_headers(),
        json={"batch_size": 1},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["inserted_count"] == 1
    assert applied.json()["remaining_valid_rows"] == 0
    assert applied.json()["batch"]["status"] == "applied_with_errors"


def test_csv_import_batch_apply_confirmed_hits_stats_export_and_filters(
    client: TestClient,
) -> None:
    csv = "\n".join(
        [
            "amount_yuan,merchant,category,note,expense_time,tags,source",
            '19.90,CSV咖啡店,餐饮,导入早餐,2026-05-06T00:30:00Z,"外卖，咖啡",支付宝账单',
            '88.00,CSV文具店,购物,导入文具,2026-04-30T16:30:00Z,"办公",支付宝账单',
            "",
        ]
    )
    created = client.post(
        "/api/imports/csv",
        headers=app_headers(),
        files={"csv_file": ("rich-rows.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["total_rows"] == 2
    assert batch["valid_rows"] == 2
    assert batch["error_rows"] == 0

    applied = client.post(
        f"/api/imports/csv/{batch['public_id']}/apply",
        headers=app_headers(),
        json={"batch_size": 10},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["inserted_count"] == 2
    assert applied.json()["remaining_valid_rows"] == 0

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200, pending.json()
    target = next(item for item in pending.json() if item["merchant"] == "CSV咖啡店")
    assert target["status"] == "pending"
    assert target["amount_cents"] == 1990
    assert target["category"] == "餐饮"
    assert target["tags"] == "外卖, 咖啡"
    assert target["source"] == "支付宝账单"
    assert target["expense_time"] == "2026-05-06T00:30:00Z"

    confirmed = client.post(
        f"/api/expenses/{target['id']}/confirm",
        headers=app_headers(),
    )
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()["status"] == "confirmed"

    stats = client.get(
        "/api/stats/monthly?month=2026-05&tag=咖啡",
        headers=app_headers(),
    )
    assert stats.status_code == 200, stats.json()
    stats_body = stats.json()
    assert stats_body["total_amount_cents"] == 1990
    assert stats_body["count"] == 1
    assert stats_body["by_category"] == [
        {"category": "餐饮", "amount_cents": 1990, "count": 1}
    ]
    by_tag = {row["tag"]: row for row in stats_body["by_tag"]}
    assert by_tag == {
        "外卖": {"tag": "外卖", "amount_cents": 1990, "count": 1},
        "咖啡": {"tag": "咖啡", "amount_cents": 1990, "count": 1},
    }

    filtered = client.get(
        "/api/expenses/confirmed?month=2026-05&category=餐饮&tag=咖啡",
        headers=app_headers(),
    )
    assert filtered.status_code == 200, filtered.json()
    filtered_body = filtered.json()
    assert filtered_body["total"] == 1
    assert filtered_body["items"][0]["merchant"] == "CSV咖啡店"
    assert filtered_body["items"][0]["source"] == "支付宝账单"

    category_miss = client.get(
        "/api/expenses/confirmed?month=2026-05&category=购物",
        headers=app_headers(),
    )
    assert category_miss.status_code == 200, category_miss.json()
    assert category_miss.json()["total"] == 0

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮&tag=咖啡",
        headers=app_headers(),
    )
    assert exported.status_code == 200, exported.text
    assert "text/csv" in exported.headers["content-type"]
    assert "CSV咖啡店" in exported.text
    assert "支付宝账单" in exported.text
    assert "外卖, 咖啡" in exported.text
    assert "CSV文具店" not in exported.text


def test_csv_import_viewer_can_read_batch_but_cannot_create_or_apply(client: TestClient) -> None:
    created = client.post(
        "/api/imports/csv",
        headers=app_headers(),
        files={"csv_file": ("rows.csv", b"amount_yuan,merchant\n1.00,Cafe\n", "text/csv")},
    )
    assert created.status_code == 201, created.json()
    public_id = created.json()["public_id"]

    _demote_owner_ledger_to_viewer()
    read = client.get(f"/api/imports/csv/{public_id}", headers=app_headers())
    assert read.status_code == 200, read.json()

    denied_apply = client.post(
        f"/api/imports/csv/{public_id}/apply",
        headers=app_headers(),
        json={"batch_size": 1},
    )
    assert denied_apply.status_code == 403
    assert denied_apply.json()["error"] == "permission_denied"

    denied_create = client.post(
        "/api/imports/csv",
        headers=app_headers(),
        files={"csv_file": ("again.csv", b"amount_yuan,merchant\n2.00,Cafe\n", "text/csv")},
    )
    assert denied_create.status_code == 403
    assert denied_create.json()["error"] == "permission_denied"
