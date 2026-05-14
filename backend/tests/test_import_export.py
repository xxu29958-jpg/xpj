"""Tests for /web/import + /web/export.csv (PR17)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import conftest as cf
from app.main import app
from app.routes.web_app import _require_local as _web_require_local
from app.services.import_service import (
    MAX_PREVIEW_ROWS,
    import_rows,
    parse_csv_preview,
)
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CsvImportBatch, Expense


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{cf.CURRENT_UPLOAD_KEY}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200
    return int(resp.json()["id"])


# ── service unit tests ─────────────────────────────────────────────────────


def test_parse_csv_preview_accepts_amount_yuan() -> None:
    csv = "amount_yuan,merchant,category\n12.34,Starbucks,餐饮\n"
    preview = parse_csv_preview(csv)
    assert preview.valid_count == 1
    row = preview.rows[0]
    assert row.amount_cents == 1234
    assert row.merchant == "Starbucks"
    assert row.category == "餐饮"


def test_parse_csv_preview_flags_invalid_rows() -> None:
    csv = "amount_yuan,merchant\nabc,Bad\n5.00,Good\n"
    preview = parse_csv_preview(csv)
    assert preview.valid_count == 1
    assert preview.error_count == 1
    assert preview.rows[0].error and "amount_yuan" in preview.rows[0].error


def test_parse_csv_preview_requires_amount_column() -> None:
    from app.errors import AppError

    with pytest.raises(AppError):
        parse_csv_preview("merchant,note\nA,B\n")


def test_parse_csv_preview_truncates_at_limit() -> None:
    body = "amount_yuan\n" + "1.00\n" * (MAX_PREVIEW_ROWS + 5)
    preview = parse_csv_preview(body)
    assert preview.truncated is True
    assert len(preview.rows) == MAX_PREVIEW_ROWS


# ── /web/export.csv ────────────────────────────────────────────────────────


def test_web_export_csv_returns_attachment(web_client: TestClient) -> None:
    resp = web_client.get("/web/export.csv?ledger_id=owner")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    # UTF-8 BOM present so Excel opens it correctly.
    assert resp.content.startswith(b"\xef\xbb\xbf")


def test_web_export_csv_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/export.csv").status_code == 403


# ── /web/import flow ───────────────────────────────────────────────────────


def test_web_import_form_renders(web_client: TestClient) -> None:
    resp = web_client.get("/web/import?ledger_id=owner")
    assert resp.status_code == 200
    assert "导入 CSV" in resp.text


def test_web_import_preview_then_confirm_inserts_pending(web_client: TestClient) -> None:
    csv = "amount_yuan,merchant,category,note\n8.50,Cafe,餐饮,morning\n12.00,Bus,交通,\n"
    resp = web_client.post(
        "/web/import/preview",
        data={"ledger_id": "owner"},
        files={"csv_file": ("rows.csv", csv.encode("utf-8"), "text/csv")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with SessionLocal() as db:
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.tenant_id == "owner"))
        assert batch is not None
        assert batch.total_rows == 2
        assert batch.valid_rows == 2

    detail = web_client.get(f"/web/import/{batch.public_id}?ledger_id=owner")
    assert detail.status_code == 200
    assert "CSV 导入批次" in detail.text
    assert "Cafe" in detail.text
    assert "Bus" in detail.text

    confirm = web_client.post(
        f"/web/import/{batch.public_id}/apply",
        data={"ledger_id": "owner", "batch_size": "500"},
        follow_redirects=False,
    )
    assert confirm.status_code == 303
    with SessionLocal() as db:
        rows = db.execute(
            select(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        ).scalars().all()
    assert len(rows) == 2
    assert {r.amount_cents for r in rows} == {850, 1200}
    assert all(r.status == "pending" for r in rows)


def test_web_import_batch_errors_csv(web_client: TestClient) -> None:
    csv = "amount_yuan,merchant,category\nabc,Bad,餐饮\n3.00,Good,交通\n"
    response = web_client.post(
        "/web/import/preview",
        data={"ledger_id": "owner"},
        files={"csv_file": ("rows.csv", csv.encode("utf-8"), "text/csv")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        batch = db.scalar(select(CsvImportBatch).where(CsvImportBatch.tenant_id == "owner"))
        assert batch is not None

    detail = web_client.get(f"/web/import/{batch.public_id}?ledger_id=owner&status=error")
    assert detail.status_code == 200
    assert "amount_yuan" in detail.text

    errors = web_client.get(f"/web/import/{batch.public_id}/errors.csv?ledger_id=owner")
    assert errors.status_code == 200
    assert errors.content.startswith(b"\xef\xbb\xbf")
    assert "Bad" in errors.text
    assert "amount_yuan" in errors.text


def test_web_import_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/import").status_code == 403


def test_web_import_no_secret_leak(web_client: TestClient) -> None:
    resp = web_client.get("/web/import?ledger_id=owner")
    body = resp.text
    assert cf.CURRENT_APP_TOKEN not in body
    assert cf.CURRENT_ADMIN_TOKEN not in body
    assert cf.CURRENT_UPLOAD_KEY not in body


# ── service-level smoke for import_rows directly ───────────────────────────


def test_import_rows_skips_invalid() -> None:
    preview = parse_csv_preview(
        "amount_yuan,merchant\nabc,Bad\n3.00,Good\n",
    )
    with SessionLocal() as db:
        inserted = import_rows(db, tenant_id="owner", rows=preview.rows)
    assert inserted == 1
