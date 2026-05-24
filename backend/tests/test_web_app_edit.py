"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import pytest
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
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "12.34", "merchant": "测试商家", "category": "餐饮",
              "note": "", "ledger_id": "owner"},
        follow_redirects=False,
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

    saved = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "original_currency": "USD",
            "amount_yuan": "124.00",
            "merchant": "Foreign Cafe Updated",
            "category": "餐饮",
            "note": "kept as USD",
        },
        follow_redirects=False,
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
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "not-a-number", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "请填写正确的金额" in resp.text


def test_web_confirm_without_amount_shows_chinese_error(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
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
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
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
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "-5.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "负数" in resp.text
