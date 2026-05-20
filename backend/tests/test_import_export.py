"""Tests for /web/import + /web/export.csv (PR17)."""

from __future__ import annotations

import csv as csv_module
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.routes.web_app import _require_local as _web_require_local
from app.errors import AppError
from app.services.import_service import (
    MAX_PREVIEW_ROWS,
    import_rows,
    parse_csv_preview,
)

from app.database import SessionLocal
from app.models import CsvImportBatch, Expense
from app.services.fx_rate_provider import upsert_fx_rate


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient, *, identity) -> int:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
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


def test_parse_csv_preview_accepts_foreign_currency_columns() -> None:
    csv = (
        "amount_cents,original_currency_code,original_amount_minor,"
        "exchange_rate_to_cny,exchange_rate_date,merchant,category\n"
        "0,USD,12345,7.1234,2026-05-04,Overseas Cafe,餐饮\n"
    )
    preview = parse_csv_preview(csv)
    assert preview.valid_count == 1
    row = preview.rows[0]
    assert row.amount_cents == 0
    assert row.original_currency_code == "USD"
    assert row.original_amount_minor == 12345
    assert row.exchange_rate_to_cny is None
    assert row.exchange_rate_date and row.exchange_rate_date.isoformat() == "2026-05-04"


def test_parse_csv_preview_treats_naive_time_as_configured_local_time() -> None:
    csv = "amount_yuan,merchant,expense_time\n1.00,Cafe,2026-05-01 00:30:00\n"
    preview = parse_csv_preview(csv, timezone_name="Asia/Shanghai")

    assert preview.valid_count == 1
    assert preview.rows[0].expense_time == datetime(2026, 4, 30, 16, 30, tzinfo=UTC)


def test_parse_csv_preview_derives_fx_date_from_local_spending_day() -> None:
    csv = (
        "amount_cents,original_currency_code,exchange_rate_to_cny,merchant,expense_time\n"
        "12345,USD,7.0000,Overseas Cafe,2026-05-04T16:30:00Z\n"
    )
    preview = parse_csv_preview(csv, timezone_name="Asia/Shanghai")

    assert preview.valid_count == 1
    assert preview.rows[0].expense_time == datetime(2026, 5, 4, 16, 30, tzinfo=UTC)
    assert preview.rows[0].exchange_rate_date
    assert preview.rows[0].exchange_rate_date.isoformat() == "2026-05-05"


def test_parse_csv_preview_expense_time_overrides_legacy_fx_date() -> None:
    csv = (
        "amount_cents,original_currency_code,exchange_rate_to_cny,exchange_rate_date,merchant,expense_time\n"
        "12345,USD,7.0000,2026-04-30,Overseas Cafe,2026-04-30T16:30:00Z\n"
    )
    preview = parse_csv_preview(csv, timezone_name="Asia/Shanghai")

    assert preview.valid_count == 1
    assert preview.rows[0].exchange_rate_date
    assert preview.rows[0].exchange_rate_date.isoformat() == "2026-05-01"


def test_parse_csv_preview_flags_invalid_rows() -> None:
    csv = "amount_yuan,merchant\nabc,Bad\n5.00,Good\n"
    preview = parse_csv_preview(csv)
    assert preview.valid_count == 1
    assert preview.error_count == 1
    assert preview.rows[0].error and "amount_yuan" in preview.rows[0].error


def test_parse_csv_preview_rejects_dirty_exchange_rate_date() -> None:
    csv = (
        "amount_cents,original_currency_code,original_amount_minor,"
        "exchange_rate_to_cny,exchange_rate_date,merchant\n"
        "0,USD,12345,7.1234,2026-05-04xxx,Dirty Date Cafe\n"
    )
    preview = parse_csv_preview(csv)
    assert preview.valid_count == 0
    assert preview.error_count == 1
    assert "exchange_rate_date" in (preview.rows[0].error or "")


def test_parse_csv_preview_converts_csv_reader_errors_to_invalid_request() -> None:
    old_limit = csv_module.field_size_limit()
    csv_module.field_size_limit(8)
    try:
        with pytest.raises(AppError) as exc_info:
            parse_csv_preview("amount_yuan,merchant\n1.00,VeryLongMerchant\n")
    finally:
        csv_module.field_size_limit(old_limit)
    assert exc_info.value.error == "invalid_request"


def test_parse_csv_preview_requires_amount_column() -> None:
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


def test_web_export_csv_neutralizes_formula_cells(web_client: TestClient) -> None:
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="owner",
                amount_cents=1200,
                merchant='=HYPERLINK("http://example.invalid")',
                category="餐饮",
                note="@note",
                source="+source",
                tags="-tag",
                status="confirmed",
                expense_time=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                created_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                confirmed_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
            )
        )
        db.commit()

    resp = web_client.get("/web/export.csv?ledger_id=owner&month=2026-05&timezone=UTC")

    assert resp.status_code == 200
    assert "'=HYPERLINK" in resp.text
    assert "'@note" in resp.text
    assert "'+source" in resp.text
    assert "'-tag" in resp.text


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
    assert "%25E" not in resp.headers["location"]
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
    csv = 'amount_yuan,merchant,category\nabc,"=HYPERLINK(""http://x"")",餐饮\n3.00,Good,交通\n'
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
    assert "'=HYPERLINK" in errors.text
    assert "amount_yuan" in errors.text


def test_web_import_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/import").status_code == 403


def test_web_import_no_secret_leak(web_client: TestClient, *, identity) -> None:
    resp = web_client.get("/web/import?ledger_id=owner")
    body = resp.text
    assert identity.app_token not in body
    assert identity.admin_token not in body
    assert identity.upload_key not in body


# ── service-level smoke for import_rows directly ───────────────────────────


def test_import_rows_skips_invalid() -> None:
    preview = parse_csv_preview(
        "amount_yuan,merchant\nabc,Bad\n3.00,Good\n",
    )
    with SessionLocal() as db:
        inserted = import_rows(db, tenant_id="owner", rows=preview.rows)
    assert inserted == 1


def test_import_rows_persists_foreign_currency_metadata() -> None:
    preview = parse_csv_preview(
        "amount_cents,original_currency_code,original_amount_minor,"
        "exchange_rate_to_cny,exchange_rate_date,merchant\n"
        "0,JPY,1200,0.048,2026-05-04,Tokyo Metro\n",
    )
    with SessionLocal() as db:
        upsert_fx_rate(
            db,
            currency_code="JPY",
            rate_date=preview.rows[0].exchange_rate_date,
            rate_to_home=Decimal("0.048"),
        )
        db.commit()
        inserted = import_rows(db, tenant_id="owner", rows=preview.rows)
        rows = db.execute(
            select(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
            .where(Expense.merchant == "Tokyo Metro")
        ).scalars().all()
    assert inserted == 1
    assert len(rows) == 1
    expense = rows[0]
    assert expense.amount_cents == 5760
    assert expense.original_currency_code == "JPY"
    assert expense.original_amount_minor == 1200
    assert str(expense.exchange_rate_to_cny) == "0.04800000"
