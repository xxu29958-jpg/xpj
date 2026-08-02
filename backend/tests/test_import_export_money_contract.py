"""C07 money-envelope and zero-decimal home-currency import/export tests."""

from __future__ import annotations

import csv as csv_module
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import CsvImportBatch, CsvImportRow, Expense
from app.money_contract import MONEY_MINOR_MAX
from app.routes.web_app import _require_local as _web_require_local
from app.services.import_service import parse_csv_preview
from tests._infra.currency import activate_test_currency_authority


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_parse_csv_preview_uses_the_c07_minor_limit_not_the_legacy_int32_limit() -> None:
    preview = parse_csv_preview(
        "amount_cents,merchant\n"
        f"2147483648,Above int32\n{MONEY_MINOR_MAX},At C07 max\n"
        f"{MONEY_MINOR_MAX + 1},Above C07 max\n"
    )

    assert preview.valid_count == 2
    assert preview.error_count == 1
    assert [row.amount_cents for row in preview.rows[:2]] == [
        2_147_483_648,
        MONEY_MINOR_MAX,
    ]
    assert preview.rows[2].amount_cents is None
    assert "超出当前版本可支持范围" in (preview.rows[2].error or "")


def test_parse_csv_preview_rejects_legacy_cny_amount_in_non_cny_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        preview = parse_csv_preview("amount_yuan,merchant\n12.34,Tokyo\n")
        assert preview.valid_count == 0
        row = preview.rows[0]
        assert row.error_code == "client_upgrade_required"
        assert row.amount_cents is None
        assert row.original_amount_minor is None
    finally:
        get_settings.cache_clear()


@pytest.mark.currency_binding_unbound
def test_csv_export_preserves_legacy_column_and_adds_exact_jpy_home_value(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        with SessionLocal() as db:
            activate_test_currency_authority(db, "JPY")
            db.add(
                Expense(
                    tenant_id="owner",
                    amount_cents=1234,
                    home_currency_code="JPY",
                    original_currency_code="JPY",
                    original_amount_minor=1234,
                    exchange_rate_to_cny=Decimal("1"),
                    exchange_rate_source="base",
                    merchant="Tokyo",
                    category="餐饮",
                    note="",
                    source="pytest",
                    status="confirmed",
                    expense_time=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                    created_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                    confirmed_at=datetime(2026, 5, 4, 0, 0, tzinfo=UTC),
                )
            )
            db.commit()

        response = web_client.get(
            "/web/export.csv?ledger_id=owner&month=2026-05&timezone=UTC"
        )
        assert response.status_code == 200
        rows = list(
            csv_module.DictReader(StringIO(response.text.lstrip("\ufeff")))
        )
        exported = next(row for row in rows if row["merchant"] == "Tokyo")

        assert exported["amount_cents"] == "1234"
        assert exported["amount_yuan"] == ""
        assert exported["home_currency_code"] == "JPY"
        assert exported["amount_home_major"] == "1234"

        preview = parse_csv_preview(response.text)
        imported = next(row for row in preview.rows if row.merchant == "Tokyo")
        assert imported.is_valid
        assert imported.amount_cents == 1234
        assert imported.original_currency_code == "JPY"
        assert imported.original_amount_minor == 1234
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("currency", ["JPY", "KRW"])
def test_parse_csv_preview_round_trips_zero_decimal_home_money_exactly(
    monkeypatch: pytest.MonkeyPatch,
    currency: str,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency)
    get_settings.cache_clear()
    try:
        preview = parse_csv_preview(
            "amount_cents,amount_yuan,home_currency_code,"
            "amount_home_major,merchant\n"
            f"{MONEY_MINOR_MAX},,{currency},{MONEY_MINOR_MAX},Boundary\n"
        )
        assert preview.valid_count == 1
        assert preview.rows[0].amount_cents == MONEY_MINOR_MAX
        assert preview.rows[0].original_amount_minor == MONEY_MINOR_MAX
    finally:
        get_settings.cache_clear()


def test_parse_csv_preview_rejects_cross_home_currency_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        preview = parse_csv_preview(
            "amount_cents,home_currency_code,amount_home_major\n"
            "1234,CNY,12.34\n"
        )
        assert preview.valid_count == 0
        assert preview.rows[0].error_code == "client_upgrade_required"
        assert preview.rows[0].amount_cents is None
    finally:
        get_settings.cache_clear()


@pytest.mark.currency_binding_unbound
def test_web_import_preview_uses_current_server_jpy_contract(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        response = web_client.post(
            "/web/import/preview",
            data={"ledger_id": "owner"},
            files={
                "csv_file": (
                    "jpy.csv",
                    (
                        b"amount_cents,home_currency_code,"
                        b"amount_home_major,merchant\n"
                        b"1234,JPY,1234,Tokyo\n"
                    ),
                    "text/csv",
                )
            },
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        location = unquote(response.headers["location"])
        assert "已解析+1+行，1+行可导入。" in location
        with SessionLocal() as db:
            batch = db.scalar(
                select(CsvImportBatch)
                .where(CsvImportBatch.tenant_id == "owner")
                .where(CsvImportBatch.file_name == "jpy.csv")
            )
            assert batch is not None
            assert batch.status == "parsed"
            assert (batch.total_rows, batch.valid_rows, batch.error_rows) == (1, 1, 0)
            row = db.scalar(
                select(CsvImportRow).where(CsvImportRow.batch_id == batch.id)
            )
            assert row is not None
            assert row.status == "valid"
            assert row.amount_cents == 1234
            assert row.original_currency_code == "JPY"
            assert row.original_amount_minor == 1234
    finally:
        get_settings.cache_clear()
