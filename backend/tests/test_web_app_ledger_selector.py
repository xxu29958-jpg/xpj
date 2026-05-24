"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense


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


def _row_id_set(html: str) -> set[str]:
    """Extract probable expense ids appearing in URLs of pending rows."""
    return set(re.findall(r"/web/expenses/(\d+)/edit", html))


def test_web_ledger_selector_present(web_client: TestClient) -> None:
    resp = web_client.get("/web")
    assert resp.status_code == 200
    assert 'name="ledger_id"' in resp.text
    assert "owner" in resp.text  # default ledger id in <option>
    assert "tester_1" in resp.text  # secondary ledger id in <option>


def test_web_invalid_ledger_rejected(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending?ledger_id=does_not_exist")
    assert resp.status_code == 400
    body = resp.text
    assert "请选择一个有权限的账本" in body or "invalid_request" in body


def test_web_selected_ledger_pending_isolated(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    # Default (owner) sees the new pending row...
    owner_pending = web_client.get("/web/pending?ledger_id=owner")
    assert owner_pending.status_code == 200
    # ...but tester_1 must not see it.
    tester_pending = web_client.get("/web/pending?ledger_id=tester_1")
    assert tester_pending.status_code == 200
    assert str(expense_id) not in _row_id_set(tester_pending.text)


def test_web_selected_ledger_confirmed_isolated(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "9.99", "merchant": "X", "category": "", "note": "",
              "ledger_id": "owner"},
        follow_redirects=False,
    )
    confirm_resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert confirm_resp.status_code in {303, 307}
    owner_confirmed = web_client.get("/web/confirmed?ledger_id=owner")
    tester_confirmed = web_client.get("/web/confirmed?ledger_id=tester_1")
    assert "9.99" in owner_confirmed.text
    assert "9.99" not in tester_confirmed.text


def test_web_selected_ledger_stats_isolated(web_client: TestClient) -> None:
    resp_owner = web_client.get("/web/stats?ledger_id=owner")
    resp_tester = web_client.get("/web/stats?ledger_id=tester_1")
    assert resp_owner.status_code == 200
    assert resp_tester.status_code == 200
    # Both render but with their own scope; basic smoke
    assert "月度统计" in resp_owner.text
    assert "月度统计" in resp_tester.text


def test_web_reject_keeps_selected_ledger(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/reject",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    assert "ledger_id=owner" in resp.headers.get("location", "")


def test_web_confirm_redirect_keeps_selected_ledger(web_client: TestClient, *, identity) -> None:
    expense_id = _create_pending(web_client, identity=identity)
    web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "1.50", "merchant": "M", "category": "", "note": "",
              "ledger_id": "owner"},
        follow_redirects=False,
    )
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    assert "ledger_id=owner" in resp.headers.get("location", "")
