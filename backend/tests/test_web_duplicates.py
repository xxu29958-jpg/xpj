"""Tests for /web/duplicates side-by-side review (PR18)."""

from __future__ import annotations

import pytest
from api_contract_helpers import confirm_expense_api, patch_expense, web_duplicates_action
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local


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


def _seed_duplicate_with_confirmed_original(
    web_client: TestClient, *, identity
) -> tuple[int, int]:
    original = _create_pending(web_client, identity=identity)
    completed = patch_expense(
        web_client,
        original,
        headers=identity.app_headers,
        fields={
            "amount_cents": 1851,
            "merchant": "已入账参考记录",
            "category": "餐饮",
            "expense_time": "2026-05-04T08:23:25Z",
        },
    )
    assert completed.status_code == 200, completed.text
    confirmed = confirm_expense_api(
        web_client,
        original,
        headers=identity.app_headers,
    )
    assert confirmed.status_code == 200, confirmed.text

    current = _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        row = db.get(Expense, current)
        assert row is not None
        assert row.duplicate_status == "suspected"
        assert row.duplicate_of_id == original
    return original, current


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
    assert "保留两条" in body
    assert "图片一致" in body
    assert "% 相似" not in body
    assert "置信度" not in body
    assert f'name="original_expense_id" value="{first}"' in body
    with SessionLocal() as db:
        original = db.get(Expense, first)
        assert original is not None
        assert (
            f'name="expected_original_row_version" value="{original.row_version}"'
            in body
        )


def test_web_duplicates_does_not_offer_reject_for_confirmed_original(
    web_client: TestClient, *, identity
) -> None:
    original, current = _seed_duplicate_with_confirmed_original(
        web_client,
        identity=identity,
    )

    body = web_client.get("/web/duplicates?ledger_id=owner").text

    assert f"/web/duplicates/{current}/reject-original" not in body
    assert "已入账参考记录不能在重复核对中忽略" in body
    assert f'name="original_expense_id" value="{original}"' not in body


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
    with SessionLocal() as db:
        before = db.scalar(select(Expense).where(Expense.id == second))
        assert before is not None
        before_row_version = before.row_version
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
        assert kept.row_version == before_row_version + 1
        assert rejected.status == "rejected"


def test_web_duplicates_confirmed_original_never_dispatches_generic_reject(
    web_client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    original, current = _seed_duplicate_with_confirmed_original(
        web_client,
        identity=identity,
    )
    current_token = _token(web_client, current, identity=identity)
    original_token = _token(web_client, original, identity=identity)

    def fail_if_dispatched(*args, **kwargs):
        raise AssertionError("confirmed original reached retired generic reject")

    monkeypatch.setattr(
        "app.services.expense_review_command_service.reject_expense",
        fail_if_dispatched,
    )
    response = web_client.post(
        f"/web/duplicates/{current}/reject-original",
        data={
            "ledger_id": "owner",
            "expected_row_version": current_token,
            "original_expense_id": original,
            "expected_original_row_version": original_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "flash_type=error" in response.headers["location"]
    with SessionLocal() as db:
        kept = db.get(Expense, current)
        reference = db.get(Expense, original)
        assert kept is not None and reference is not None
        assert kept.status == "pending"
        assert kept.duplicate_status == "suspected"
        assert kept.duplicate_of_id == original
        assert reference.status == "confirmed"


def test_web_duplicates_reject_original_is_atomic(
    web_client: TestClient, *, identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = _seed_duplicate_pair(web_client, identity=identity)
    token = _token(web_client, second, identity=identity)
    original_token = _token(web_client, first, identity=identity)

    def fail_reject(*args, **kwargs):
        raise AppError("state_conflict", status_code=409)

    monkeypatch.setattr(
        "app.services.expense_review_command_service.reject_expense",
        fail_reject,
    )
    resp = web_client.post(
        f"/web/duplicates/{second}/reject-original",
        data={
            "ledger_id": "owner",
            "expected_row_version": token,
            "original_expense_id": first,
            "expected_original_row_version": original_token,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash_type=error" in resp.headers.get("location", "")

    with SessionLocal() as db:
        kept = db.scalar(select(Expense).where(Expense.id == second))
        original = db.scalar(select(Expense).where(Expense.id == first))
        assert kept is not None and original is not None
        assert kept.duplicate_status == "suspected"
        assert kept.duplicate_of_id == first
        assert kept.row_version == int(token)
        assert original.status == "pending"

    monkeypatch.undo()
    changed = patch_expense(
        web_client,
        first,
        headers=identity.app_headers,
        fields={"note": "Concurrent Original Truth"},
    )
    assert changed.status_code == 200, changed.text

    stale = web_client.post(
        f"/web/duplicates/{second}/reject-original",
        data={
            "ledger_id": "owner",
            "expected_row_version": token,
            "original_expense_id": first,
            "expected_original_row_version": original_token,
        },
        follow_redirects=False,
    )
    assert stale.status_code == 303
    assert "flash_type=error" in stale.headers.get("location", "")
    with SessionLocal() as db:
        kept = db.get(Expense, second)
        original = db.get(Expense, first)
        assert kept is not None and original is not None
        assert kept.duplicate_status == "suspected"
        assert kept.duplicate_of_id == first
        assert kept.row_version == int(token)
        assert original.status == "pending"
        assert original.note == "Concurrent Original Truth"


def test_web_duplicates_stale_token_renders_error_style(web_client: TestClient, *, identity) -> None:
    """S4-R1: 判定动作遇 stale OCC token 时, 重定向带 flash_type=error, 页面按
    错误样式渲染且文案保留 (此前一律绿成功, 「已在其它端被修改」被误读为成功);
    成功动作仍按成功样式渲染。"""
    _, second = _seed_duplicate_pair(web_client, identity=identity)

    stale = web_client.post(
        f"/web/duplicates/{second}/keep",
        data={"ledger_id": "owner", "expected_row_version": "not-a-token"},
        follow_redirects=False,
    )
    assert stale.status_code == 303
    location = stale.headers.get("location", "")
    assert "flash_type=error" in location
    page = web_client.get(location)
    assert page.status_code == 200
    assert "product-feedback--error" in page.text
    assert "账单已在其它端被修改" in page.text

    token = _token(web_client, second, identity=identity)
    ok = web_client.post(
        f"/web/duplicates/{second}/keep",
        data={"ledger_id": "owner", "expected_row_version": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    ok_location = ok.headers.get("location", "")
    assert "flash_type=success" in ok_location
    ok_page = web_client.get(ok_location)
    assert "product-feedback--success" in ok_page.text


def test_web_duplicates_missing_reason_shows_honest_fallback(
    web_client: TestClient, *, identity
) -> None:
    """S4-R2: legacy 空 reason 不捏造「多项字段相似」证据 — 空/未识别 reason
    诚实兜底「系统未提供判定原因」。"""
    _, second = _seed_duplicate_pair(web_client, identity=identity)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        row.duplicate_reason = None
        db.commit()

    resp = web_client.get("/web/duplicates?ledger_id=owner")
    assert resp.status_code == 200
    assert "系统未提供判定原因" in resp.text
    assert "待人工核对" in resp.text
    assert "70%" not in resp.text
    assert "多项账单信息相似" not in resp.text


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
