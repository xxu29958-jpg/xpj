"""Tests for /web/duplicates side-by-side review (PR18)."""

from __future__ import annotations

import pytest
from api_contract_helpers import web_duplicates_action
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local
from app.routes.web_duplicates import (
    _duplicate_expense_view,
    _duplicate_reason_label,
)


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient, *, identity) -> int:
    """Upload the same tiny PNG twice in a row produces a suspected duplicate
    on the second row (image hash match)."""
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


def _seed_duplicate_pair(web_client: TestClient, *, identity) -> tuple[int, int]:
    first = _create_pending(web_client, identity=identity)
    second = _create_pending(web_client, identity=identity)
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


def test_web_duplicates_renders_pair(web_client: TestClient, *, identity) -> None:
    first, second = _seed_duplicate_pair(web_client, identity=identity)
    resp = web_client.get("/web/duplicates?ledger_id=owner")
    assert resp.status_code == 200
    body = resp.text
    assert f"#{second}" in body
    assert f"#{first}" in body
    assert "不是重复，保留两条" in body
    assert "<h2>参考记录</h2>" in body
    assert "<h2>当前待核对记录</h2>" in body
    assert body.count("待确认") >= 2
    assert "两张图片完全一致" in body
    assert "忽略参考记录" in body
    assert "忽略当前记录" in body
    assert "原账单" not in body
    assert "新草稿" not in body
    assert 'data-domain="inbox"' in body
    assert 'class="duplicate-compare"' in body
    assert 'name="csrf_token"' in body
    assert "dt-card" not in body
    assert 'class="dt-' not in body
    assert 'style="' not in body


def test_web_duplicates_renders_each_record_actual_status(
    web_client: TestClient,
    *,
    identity,
) -> None:
    first, _ = _seed_duplicate_pair(web_client, identity=identity)
    with SessionLocal() as db:
        original = db.scalar(select(Expense).where(Expense.id == first))
        assert original is not None
        original.status = "confirmed"
        db.commit()

    body = web_client.get("/web/duplicates?ledger_id=owner").text
    reference = body.split("<h2>参考记录</h2>", maxsplit=1)[1].split(
        '<article class="duplicate-record duplicate-record--draft">',
        maxsplit=1,
    )[0]
    current = body.split(
        '<article class="duplicate-record duplicate-record--draft">',
        maxsplit=1,
    )[1]
    assert "已入账" in reference
    assert "待确认" in current


def test_web_duplicates_unknown_status_and_reason_use_product_fallbacks() -> None:
    expense = type(
        "ExpenseStub",
        (),
        {
            "amount_cents": 100,
            "home_currency_code": "CNY",
            "original_currency_code": "CNY",
            "original_amount_minor": None,
            "image_path": None,
            "image_deleted_at": None,
            "source": "",
            "merchant": "",
            "category": "",
            "note": "",
            "tags": "",
            "status": "future_status",
            "expense_time": None,
            "updated_at": None,
            "row_version": 1,
            "created_at": None,
            "duplicate_status": "suspected",
            "id": 1,
        },
    )()
    view = _duplicate_expense_view(expense)
    assert view["status_label"] == "状态待确认"
    assert view["status_tone"] == ""
    assert _duplicate_reason_label("future_reason_code") == "多项账单信息相似"


# ── Loopback gate + secret leak ────────────────────────────────────────────


def test_web_duplicates_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/duplicates").status_code == 403
    assert client.post("/web/duplicates/1/keep").status_code == 403
    assert client.post("/web/duplicates/1/reject-current").status_code == 403
    assert client.post("/web/duplicates/1/reject-original").status_code == 403


def test_web_duplicates_no_secret_leak(web_client: TestClient, *, identity) -> None:
    _seed_duplicate_pair(web_client, identity=identity)
    body = web_client.get("/web/duplicates?ledger_id=owner").text
    assert identity.app_token not in body
    assert identity.admin_token not in body
    assert identity.upload_key not in body


# ── Action: keep both ──────────────────────────────────────────────────────


def test_web_duplicates_keep_both_clears_flag(web_client: TestClient, *, identity) -> None:
    _, second = _seed_duplicate_pair(web_client, identity=identity)
    resp = web_duplicates_action(
        web_client, second, identity=identity, action="keep"
    )
    assert resp.status_code == 303
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "none"
        assert row.duplicate_of_id is None


# ── Action: reject current ─────────────────────────────────────────────────


def test_web_duplicates_reject_current_marks_rejected(web_client: TestClient, *, identity) -> None:
    first, second = _seed_duplicate_pair(web_client, identity=identity)
    resp = web_duplicates_action(
        web_client, second, identity=identity, action="reject-current"
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


def test_web_duplicates_reject_original_keeps_current(web_client: TestClient, *, identity) -> None:
    first, second = _seed_duplicate_pair(web_client, identity=identity)
    resp = web_duplicates_action(
        web_client, second, identity=identity, action="reject-original"
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


# ── 批10: keep via the pending drawer fetch-mutation ────────────────────────


def _token(web_client: TestClient, expense_id: int, *, identity) -> str:
    snapshot = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert snapshot.status_code == 200, snapshot.text
    return str(snapshot.json()["row_version"])


def test_web_duplicate_keep_fragment_success_returns_marker(
    web_client: TestClient, *, identity
) -> None:
    """批10: the pending drawer's 「标为非重复」 button posts here with fragment=1;
    success returns a 200 marker (the client re-fetches the now-unflagged drawer),
    not a redirect, and the flag is actually cleared."""
    _, second = _seed_duplicate_pair(web_client, identity=identity)
    resp = web_client.post(
        f"/web/duplicates/{second}/keep",
        data={"ledger_id": "owner", "expected_row_version": _token(
            web_client, second, identity=identity
        ), "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert 'data-drawer-ok="keep"' in resp.text
    assert not resp.text.lstrip().startswith("{")
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "none"


def test_web_duplicate_keep_fragment_missing_expense_returns_readable_html(
    web_client: TestClient,
) -> None:
    """批10: a fetch-keep on a vanished row degrades to the readable empty-cell
    snippet at the row's status, not bare JSON injected into the drawer."""
    resp = web_client.post(
        "/web/duplicates/99999/keep",
        data={"ledger_id": "owner", "expected_row_version": "1", "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 404, resp.text
    assert "empty-cell" in resp.text
    assert not resp.text.lstrip().startswith("{")
