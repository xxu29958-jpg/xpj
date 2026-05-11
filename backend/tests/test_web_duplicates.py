"""Tests for /web/duplicates side-by-side review (PR18)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import conftest as cf
from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient) -> int:
    """Upload the same tiny PNG twice in a row produces a suspected duplicate
    on the second row (image hash match)."""
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


def _seed_duplicate_pair(web_client: TestClient) -> tuple[int, int]:
    first = _create_pending(web_client)
    second = _create_pending(web_client)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "suspected"
        assert row.duplicate_of_id == first
    return first, second


# ── Page rendering ─────────────────────────────────────────────────────────


def test_web_duplicates_renders_empty(web_client: TestClient) -> None:
    resp = web_client.get("/web/duplicates?ledger_id=owner")
    assert resp.status_code == 200
    assert "没有疑似重复" in resp.text


def test_web_duplicates_renders_pair(web_client: TestClient) -> None:
    first, second = _seed_duplicate_pair(web_client)
    resp = web_client.get("/web/duplicates?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert f"#{second}" in body
    assert f"#{first}" in body
    assert "保留两条" in body


# ── Loopback gate + secret leak ────────────────────────────────────────────


def test_web_duplicates_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/duplicates").status_code == 403
    assert client.post("/web/duplicates/1/keep").status_code == 403
    assert client.post("/web/duplicates/1/reject-current").status_code == 403
    assert client.post("/web/duplicates/1/reject-original").status_code == 403


def test_web_duplicates_no_secret_leak(web_client: TestClient) -> None:
    _seed_duplicate_pair(web_client)
    body = web_client.get("/web/duplicates?ledger_id=owner").text
    assert cf.CURRENT_APP_TOKEN not in body
    assert cf.CURRENT_ADMIN_TOKEN not in body
    assert cf.CURRENT_UPLOAD_KEY not in body


# ── Action: keep both ──────────────────────────────────────────────────────


def test_web_duplicates_keep_both_clears_flag(web_client: TestClient) -> None:
    _, second = _seed_duplicate_pair(web_client)
    resp = web_client.post(
        f"/web/duplicates/{second}/keep",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "none"
        assert row.duplicate_of_id is None


# ── Action: reject current ─────────────────────────────────────────────────


def test_web_duplicates_reject_current_marks_rejected(web_client: TestClient) -> None:
    first, second = _seed_duplicate_pair(web_client)
    resp = web_client.post(
        f"/web/duplicates/{second}/reject-current",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.status == "rejected"
        # Original untouched.
        original = db.scalar(select(Expense).where(Expense.id == first))
        assert original is not None
        assert original.status == "pending"


# ── Action: reject original ────────────────────────────────────────────────


def test_web_duplicates_reject_original_keeps_current(web_client: TestClient) -> None:
    first, second = _seed_duplicate_pair(web_client)
    resp = web_client.post(
        f"/web/duplicates/{second}/reject-original",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    with SessionLocal() as db:
        kept = db.scalar(select(Expense).where(Expense.id == second))
        rejected = db.scalar(select(Expense).where(Expense.id == first))
        assert kept is not None and rejected is not None
        assert kept.status == "pending"
        assert kept.duplicate_status == "none"
        assert kept.duplicate_of_id is None
        assert rejected.status == "rejected"


def test_web_duplicates_unknown_id_returns_friendly_msg(web_client: TestClient) -> None:
    # ``mark_expense_not_duplicate`` raises AppError(404) — route catches it
    # and surfaces the message via redirect.
    resp = web_client.post(
        "/web/duplicates/99999/keep",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "msg=" in resp.headers.get("location", "")
