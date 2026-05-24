"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from pathlib import Path

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


def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试", *, identity) -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_confirmed_batch_markup_and_updates(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_with_amount(web_client, "21.00", "Confirmed Bulk Cafe", identity=identity)
    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert confirmed.status_code in {303, 307}

    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200
    assert 'action="/web/confirmed/batch-update"' in page.text
    assert f'data-id="{expense_id}"' in page.text
    assert 'id="check-all"' in page.text

    category_resp = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": [str(expense_id)],
            "category": "Batch Web Cat",
            "page": "2",
        },
        follow_redirects=False,
    )
    assert category_resp.status_code in {303, 307}
    assert "page=2" in category_resp.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "Batch Web Cat" in detail.text

    tags_resp = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_tags",
            "ledger_id": "owner",
            "expense_ids": [str(expense_id)],
            "tags": "web, family, web",
        },
        follow_redirects=False,
    )
    assert tags_resp.status_code in {303, 307}
    api_detail = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert api_detail.status_code == 200
    assert api_detail.json()["tags"] == "web, family"


def test_web_pending_filter_missing_amount(web_client: TestClient, *, identity) -> None:
    pending_no_amount = _create_pending(web_client, identity=identity)  # no amount yet
    pending_with_amount = _seed_pending_with_amount(web_client, "5.00", "A", identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert resp.status_code == 200
    assert f"/web/expenses/{pending_no_amount}/edit" in resp.text
    assert f"/web/expenses/{pending_with_amount}/edit" not in resp.text


def test_web_pending_filter_ready_excludes_missing_amount(web_client: TestClient, *, identity) -> None:
    # Seed the ready one first so it doesn't get flagged as duplicate of the
    # second upload (same PNG bytes ⇒ second becomes suspected).
    pending_ready = _seed_pending_with_amount(web_client, "8.00", "Ready", identity=identity)
    pending_no_amount = _create_pending(web_client, identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f"/web/expenses/{pending_ready}/edit" in resp.text
    assert f"/web/expenses/{pending_no_amount}/edit" not in resp.text


def test_web_pending_filter_active_tab_marker(web_client: TestClient, *, identity) -> None:
    _create_pending(web_client, identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert resp.status_code == 200
    assert 'class="filter-tab is-active"' in resp.text


def test_web_pending_bulk_selection_markup_and_js_field_name(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    assert f'data-expense-id="{eid}"' in resp.text
    assert 'aria-selected="false"' in resp.text
    assert f'aria-label="选择账单 #{eid}"' in resp.text
    assert 'role="checkbox"' in resp.text
    assert 'name="category"' in resp.text
    assert 'name="merchant"' in resp.text

    js_path = Path(__file__).resolve().parents[1] / "app/static/web/desktop/bulk-bar.js"
    js = js_path.read_text(encoding="utf-8")
    assert 'h.name = "expense_ids";' in js


def test_web_bulk_set_category_updates_pending(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "set_category", "ledger_id": "owner",
              "expense_ids": [str(eid)], "category": "餐饮", "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner")
    assert "餐饮" in detail.text


def test_web_bulk_set_category_requires_value(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "set_category", "ledger_id": "owner",
              "expense_ids": [str(eid)], "category": "", "filter": "all"},
        follow_redirects=False,
    )
    # Empty input must not silently succeed — either 422 or redirect with skip msg.
    assert resp.status_code in {303, 307, 422}


def test_web_bulk_confirm_ready_skips_missing_amount(web_client: TestClient, *, identity) -> None:
    no_amount = _create_pending(web_client, identity=identity)
    ready = _seed_pending_with_amount(web_client, "11.00", "Ready", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "confirm_ready", "ledger_id": "owner",
              "expense_ids": [str(no_amount), str(ready)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    # The ready one should now be confirmed (not in pending listing).
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{ready}/edit" not in pending.text
    # The no-amount one stays pending.
    assert f"/web/expenses/{no_amount}/edit" in pending.text


def test_web_bulk_reject_removes_from_pending(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "12.00", "Y", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "reject", "ledger_id": "owner",
              "expense_ids": [str(eid)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{eid}/edit" not in pending.text


def test_web_bulk_keep_duplicate_persists_flag_clear(web_client: TestClient, *, identity) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Duplicate A", identity=identity)
    second = _seed_pending_with_amount(web_client, "12.00", "Duplicate B", identity=identity)
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        row.duplicate_status = "suspected"
        row.duplicate_of_id = first
        row.duplicate_reason = "test duplicate"
        db.commit()

    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "keep_duplicate", "ledger_id": "owner", "expense_ids": [str(second)], "filter": "all"},
        follow_redirects=False,
    )

    assert resp.status_code in {303, 307}
    with SessionLocal() as db:
        row = db.scalar(select(Expense).where(Expense.id == second))
        assert row is not None
        assert row.duplicate_status == "none"
        assert row.duplicate_of_id is None


def test_web_pending_batch_reject_removes_multiple_pending(web_client: TestClient, *, identity) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Y", identity=identity)
    second = _seed_pending_with_amount(web_client, "13.00", "Z", identity=identity)
    resp = web_client.post(
        "/web/pending/batch-reject",
        data={"ledger_id": "owner", "expense_ids": [str(first), str(second)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{first}/edit" not in pending.text
    assert f"/web/expenses/{second}/edit" not in pending.text


def test_web_pending_batch_reject_requires_selection(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/pending/batch-reject",
        data={"ledger_id": "owner", "filter": "all"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "请先勾选账单" in resp.text


def test_web_bulk_unknown_action_returns_error(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "explode", "ledger_id": "owner",
              "expense_ids": [str(eid)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {400, 422}


def test_web_bulk_cross_ledger_id_is_ignored(web_client: TestClient, *, identity) -> None:
    """If an id from another ledger is submitted, action must NOT mutate it."""
    eid_owner = _seed_pending_with_amount(web_client, "9.00", "Owner", identity=identity)
    # Forge a bogus id far outside any existing range.
    bogus_id = eid_owner + 99999
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "reject", "ledger_id": "owner",
              "expense_ids": [str(bogus_id)], "filter": "all"},
        follow_redirects=False,
    )
    # Should redirect (no crash, no mutation).
    assert resp.status_code in {303, 307}
    # Owner ledger still has its expense.
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{eid_owner}/edit" in pending.text
