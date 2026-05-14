from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Expense, LedgerMember
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
    list_csv_import_rows,
)
from conftest import app_headers, gray_app_headers


def _csv_bytes(row_count: int) -> BytesIO:
    lines = ["amount_yuan,merchant,category,note,tags"]
    lines.extend(f"{index}.00,Merchant {index},餐饮,note {index},外卖" for index in range(1, row_count + 1))
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
            file_obj=_csv_bytes(1005),
        )
        assert batch.total_rows == 1005
        assert batch.valid_rows == 1005
        assert batch.error_rows == 0

        second_page = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=2,
            page_size=500,
        )
        assert second_page.total == 1005
        assert len(second_page.items) == 500
        assert second_page.items[0].line_number == 502

        first_apply = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            batch_size=700,
        )
        assert first_apply.inserted_count == 700
        assert first_apply.remaining_valid_rows == 305

        second_apply = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            batch_size=700,
        )
        assert second_apply.inserted_count == 305
        assert second_apply.remaining_valid_rows == 0
        assert second_apply.batch.status == "applied"

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
        assert inserted == 1005


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
