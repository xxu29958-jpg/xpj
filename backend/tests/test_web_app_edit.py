"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import pytest
from api_contract_helpers import web_confirm_expense, web_save_expense
from fastapi.testclient import TestClient


def _create_pending(client: TestClient, *, identity) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
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
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_web_edit_save_updates_amount(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "12.34", "merchant": "测试商家", "category": "餐饮",
              "note": "", "ledger_id": "owner"},
    )
    assert resp.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "12.34" in detail.text
    assert "测试商家" in detail.text


def test_web_edit_save_preserves_foreign_currency_fields(web_client: TestClient, *, identity) -> None:
    rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={"currency_code": "USD", "rate_date": "2026-05-04", "rate_to_cny": "7.0000"},
    )
    assert rate.status_code == 200, rate.json()
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "original_currency_code": "USD",
            "original_amount_minor": 12345,
            "merchant": "Foreign Cafe",
            "category": "餐饮",
            "expense_time": "2026-05-04T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.json()
    expense_id = int(created.json()["id"])

    saved = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "ledger_id": "owner",
            "original_currency": "USD",
            "amount_yuan": "124.00",
            "merchant": "Foreign Cafe Updated",
            "category": "餐饮",
            "note": "kept as USD",
        },
    )
    assert saved.status_code in {303, 307}, saved.text

    detail = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert detail.status_code == 200, detail.json()
    payload = detail.json()
    assert payload["original_currency_code"] == "USD"
    assert payload["original_amount_minor"] == 12400
    assert payload["amount_cents"] == 86800
    assert payload["merchant"] == "Foreign Cafe Updated"


def test_web_edit_image_uses_skeleton_placeholder(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "data-image-skeleton" in detail.text
    assert "receipt-image-skeleton" in detail.text

    drawer = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1")
    assert drawer.status_code == 200
    assert "data-image-skeleton" in drawer.text
    assert "receipt-image-skeleton" in drawer.text


def test_web_save_invalid_amount_shows_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "not-a-number", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "请填写正确的金额" in resp.text


def test_web_confirm_without_amount_shows_chinese_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_confirm_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    assert resp.status_code == 200
    assert "请先填写金额" in resp.text


@pytest.mark.parametrize(
    "input_str,expected_cents",
    [
        ("12.34", 1234),
        ("0.01", 1),
        ("0.1", 10),
        ("12.345", 1235),
        ("0.005", 1),
        ("100", 10000),
        ("0", 0),
    ],
)
def test_web_amount_decimal_precision(
    web_client: TestClient, input_str: str, expected_cents: int
, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": input_str, "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    from decimal import Decimal
    expected_display = str((Decimal(expected_cents) / Decimal("100")).quantize(Decimal("0.01")))
    assert expected_display in detail.text


def test_web_save_negative_amount_shows_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={"amount_yuan": "-5.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "负数" in resp.text


def test_web_edit_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    """A stale link / cross-ledger expense id must not render a bare-JSON
    page; the full-page form redirects back to the confirmed list."""
    resp = web_client.get(
        "/web/expenses/999999/edit?ledger_id=owner", follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/web/confirmed")


def test_web_edit_missing_expense_fragment_returns_readable_html(
    web_client: TestClient,
) -> None:
    """The drawer fetch (desktop.js does not check res.ok) must receive a
    readable HTML snippet, not raw JSON injected into the drawer."""
    resp = web_client.get(
        "/web/expenses/999999/edit?ledger_id=owner&fragment=1",
        follow_redirects=False,
    )
    assert resp.status_code == 404
    assert "没有找到这笔账单" in resp.text
    assert not resp.text.lstrip().startswith("{")


def test_web_save_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    """Audit P2 #6: the save error path re-reads the expense to re-render the
    form; for a vanished row that second read used to escape to the global
    bare-JSON handler. It must flash-redirect like the GET guard instead."""
    resp = web_client.post(
        "/web/expenses/999999/save",
        data={"amount_yuan": "1.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/confirmed")
    assert "msg=" in resp.headers["location"]
    assert not resp.text.lstrip().startswith("{")


def test_web_confirm_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/expenses/999999/confirm",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")
    assert "msg=" in resp.headers["location"]


def test_web_confirm_stale_token_on_missing_expense_redirects_with_flash(
    web_client: TestClient,
) -> None:
    """The parsed-None branch (stale form on a deleted row) shares the guard."""
    resp = web_client.post(
        "/web/expenses/999999/confirm",
        data={"ledger_id": "owner", "expected_row_version": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")


def test_web_reject_missing_expense_redirects_with_flash(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/expenses/999999/reject",
        data={"ledger_id": "owner", "expected_row_version": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"].startswith("/web/pending")
    assert "msg=" in resp.headers["location"]
