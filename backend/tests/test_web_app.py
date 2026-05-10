"""Tests for the /web MVP UI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import conftest as cf  # noqa: F401
from app.main import app
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    """Bypass the /web loopback gate for tests (peer is 'testclient')."""
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_web_index_redirects_to_pending(web_client: TestClient) -> None:
    resp = web_client.get("/web", follow_redirects=False)
    assert resp.status_code in {303, 307}
    assert "/web/pending" in resp.headers.get("location", "")


def test_web_pending_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/pending")
    assert resp.status_code == 403


def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert "待确认" in resp.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert "已入账" in resp.text


def test_web_stats_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/stats?month=2026-05")
    assert resp.status_code == 200
    assert "月度统计" in resp.text


def _create_pending(client: TestClient) -> int:
    """Helper: upload a tiny PNG to the owner ledger so /web/pending sees it."""
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
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_web_edit_save_updates_amount(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "12.34", "merchant": "测试商家", "category": "餐饮", "note": ""},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit")
    assert detail.status_code == 200
    assert "12.34" in detail.text
    assert "测试商家" in detail.text


def test_web_save_invalid_amount_shows_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "not-a-number", "merchant": "", "category": "", "note": ""},
    )
    assert resp.status_code == 200
    assert "请填写正确的金额" in resp.text


def test_web_confirm_without_amount_shows_chinese_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    # Pending row has no amount; confirm should fail with Chinese message.
    resp = web_client.post(f"/web/expenses/{expense_id}/confirm", follow_redirects=False)
    assert resp.status_code == 200  # rendered edit page with error
    assert "请先填写金额" in resp.text


def test_web_html_does_not_leak_token_hash(web_client: TestClient) -> None:
    import re

    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    matches = re.findall(r"\b[0-9a-f]{64}\b", resp.text)
    assert matches == [], f"token_hash leaked: {matches[:1]}"


# ── Decimal amount precision ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "input_str,expected_cents",
    [
        ("12.34", 1234),
        ("0.01", 1),
        ("0.1", 10),
        ("12.345", 1235),   # ROUND_HALF_UP
        ("0.005", 1),       # ROUND_HALF_UP
        ("100", 10000),
        ("0", 0),
    ],
)
def test_web_amount_decimal_precision(
    web_client: TestClient, input_str: str, expected_cents: int
) -> None:
    """Decimal-based conversion must match exact cent values (no float drift)."""
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": input_str, "merchant": "", "category": "", "note": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Re-fetch edit page and check displayed amount rounds correctly
    detail = web_client.get(f"/web/expenses/{expense_id}/edit")
    from decimal import Decimal
    expected_display = str((Decimal(expected_cents) / Decimal("100")).quantize(Decimal("0.01")))
    assert expected_display in detail.text, (
        f"input={input_str!r} expected {expected_display} in page"
    )


def test_web_save_negative_amount_shows_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "-5.00", "merchant": "", "category": "", "note": ""},
    )
    assert resp.status_code == 200
    assert "负数" in resp.text


# ── Public-boundary enforcement for /web action routes ────────────────────────

def test_web_confirm_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/web/expenses/1/confirm")
    assert resp.status_code == 403


def test_web_reject_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/web/expenses/1/reject")
    assert resp.status_code == 403


def test_web_image_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/expenses/1/image")
    assert resp.status_code == 403


def test_web_thumbnail_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/expenses/1/thumbnail")
    assert resp.status_code == 403


def test_web_save_remote_returns_403(client: TestClient) -> None:
    resp = client.post("/web/expenses/1/save", data={"amount_yuan": "1.00"})
    assert resp.status_code == 403

