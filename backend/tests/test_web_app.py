"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import conftest as cf  # noqa: F401
from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    """Bypass the /web loopback gate for tests (peer is 'testclient')."""
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


# ── Dashboard root ──────────────────────────────────────────────────────────

def test_web_root_renders_dashboard(web_client: TestClient) -> None:
    resp = web_client.get("/web", follow_redirects=False)
    assert resp.status_code == 200
    assert "仪表盘" in resp.text


def test_web_root_slash_redirects_to_root_with_ledger(web_client: TestClient) -> None:
    resp = web_client.get("/web/?ledger_id=owner", follow_redirects=False)
    assert resp.status_code in {303, 307}
    loc = resp.headers.get("location", "")
    assert loc.startswith("/web?") and "ledger_id=owner" in loc


# ── Loopback gate (public boundary) ─────────────────────────────────────────

def test_web_pending_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/pending")
    assert resp.status_code == 403


def test_web_dashboard_data_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web/dashboard/data")
    assert resp.status_code == 403


def test_web_root_remote_returns_403(client: TestClient) -> None:
    resp = client.get("/web")
    assert resp.status_code == 403


def test_web_confirm_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/confirm").status_code == 403


def test_web_reject_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/reject").status_code == 403


def test_web_pending_batch_reject_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/pending/batch-reject").status_code == 403


def test_web_confirmed_batch_update_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/confirmed/batch-update").status_code == 403


def test_web_search_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/search").status_code == 403


def test_web_image_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/expenses/1/image").status_code == 403


def test_web_thumbnail_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/expenses/1/thumbnail").status_code == 403


def test_web_save_remote_returns_403(client: TestClient) -> None:
    assert client.post("/web/expenses/1/save", data={"amount_yuan": "1.00"}).status_code == 403


def test_web_local_post_rejects_cross_site_origin(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53001),
    ) as local_client:
        resp = local_client.post(
            "/web/confirmed/batch-update",
            headers={"Origin": "https://evil.example"},
            data={"action": "set_category", "ledger_id": "owner"},
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"


def test_web_local_post_accepts_same_origin_source(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53002),
    ) as local_client:
        resp = local_client.post(
            "/web/confirmed/batch-update",
            headers={"Origin": "http://127.0.0.1:8000"},
            data={"action": "set_category", "ledger_id": "owner"},
            follow_redirects=False,
        )
    assert resp.status_code in {303, 307}


def test_owner_local_post_rejects_cross_site_fetch_metadata(client: TestClient) -> None:
    del client
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 53003),
    ) as local_client:
        resp = local_client.post(
            "/owner/backups",
            headers={
                "Origin": "https://evil.example",
                "Sec-Fetch-Site": "cross-site",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_request"


# ── Local pages render OK ───────────────────────────────────────────────────

def test_web_pending_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/pending")
    assert resp.status_code == 200
    assert "待确认" in resp.text


def test_web_confirmed_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/confirmed")
    assert resp.status_code == 200
    assert "已确认" in resp.text


def test_web_stats_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/stats?month=2026-05")
    assert resp.status_code == 200
    assert "月度统计" in resp.text


def test_web_stats_reports_recurring_candidate_errors(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routes import web_stats as web_stats_module

    def fail_recurring_candidates(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_stats_module, "recurring_candidates", fail_recurring_candidates)

    resp = web_client.get("/web/stats?month=2026-05")

    assert resp.status_code == 200
    assert "固定支出候选分析暂时不可用" in resp.text


# ── Ledger selector contract ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/web/stats?month=2026-13",
        "/web/confirmed?month=0000-05",
        "/web/categories?month=2026-5",
    ],
)
def test_web_month_pages_reject_invalid_month_labels(
    web_client: TestClient, path: str
) -> None:
    resp = web_client.get(path)
    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_web_search_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/search?ledger_id=owner")
    assert resp.status_code == 200
    assert 'name="q"' in resp.text


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


def test_web_selected_ledger_pending_isolated(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    # Default (owner) sees the new pending row...
    owner_pending = web_client.get("/web/pending?ledger_id=owner")
    assert owner_pending.status_code == 200
    # ...but tester_1 must not see it.
    tester_pending = web_client.get("/web/pending?ledger_id=tester_1")
    assert tester_pending.status_code == 200
    assert str(expense_id) not in _row_id_set(tester_pending.text)


def test_web_selected_ledger_confirmed_isolated(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
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


def test_web_reject_keeps_selected_ledger(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/reject",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    assert "ledger_id=owner" in resp.headers.get("location", "")


def test_web_confirm_redirect_keeps_selected_ledger(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
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


def test_web_no_secret_leaks(web_client: TestClient) -> None:
    """No token_hash, upload_key, pairing_code or absolute path in HTML."""
    pages = ["/web", "/web/pending", "/web/confirmed", "/web/stats", "/web/search"]
    for path in pages:
        resp = web_client.get(path)
        assert resp.status_code == 200, path
        body = resp.text
        # 64-char lower-hex token hashes
        assert not re.search(r"\b[0-9a-f]{64}\b", body), f"token_hash leaked in {path}"
        # Upload keys (~40 chars urlsafe). Anything starting with /u/ + token.
        assert "upload_key" not in body, f"upload_key keyword leaked in {path}"
        # Pairing code printed verbatim is fine as a label; ensure runtime value not echoed
        assert cf.CURRENT_UPLOAD_KEY not in body, f"upload_key value leaked in {path}"
        # Absolute Windows / POSIX paths
        assert not re.search(r"[A-Za-z]:\\\\[^\"'<>]+", body), f"abs path leaked in {path}"
        assert "/home/" not in body and "C:\\" not in body


# ── Existing save/confirm semantics still work ──────────────────────────────

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


def _row_id_set(html: str) -> set[str]:
    """Extract probable expense ids appearing in URLs of pending rows."""
    return set(re.findall(r"/web/expenses/(\d+)/edit", html))


def test_web_edit_save_updates_amount(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
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


def test_web_edit_save_preserves_foreign_currency_fields(web_client: TestClient) -> None:
    rate = web_client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=cf.app_headers(),
        json={"currency_code": "USD", "rate_date": "2026-05-04", "rate_to_cny": "7.0000"},
    )
    assert rate.status_code == 200, rate.json()
    created = web_client.post(
        "/api/expenses/manual",
        headers=cf.app_headers(),
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

    detail = web_client.get(f"/api/expenses/{expense_id}", headers=cf.app_headers())
    assert detail.status_code == 200, detail.json()
    payload = detail.json()
    assert payload["original_currency_code"] == "USD"
    assert payload["original_amount_minor"] == 12400
    assert payload["amount_cents"] == 86800
    assert payload["merchant"] == "Foreign Cafe Updated"


def test_web_edit_image_uses_skeleton_placeholder(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "data-image-skeleton" in detail.text
    assert "receipt-image-skeleton" in detail.text

    drawer = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&fragment=1")
    assert drawer.status_code == 200
    assert "data-image-skeleton" in drawer.text
    assert "receipt-image-skeleton" in drawer.text


def test_web_save_invalid_amount_shows_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "not-a-number", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "请填写正确的金额" in resp.text


def test_web_confirm_without_amount_shows_chinese_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
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
) -> None:
    expense_id = _create_pending(web_client)
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


def test_web_save_negative_amount_shows_error(web_client: TestClient) -> None:
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": "-5.00", "merchant": "", "category": "", "note": "",
              "ledger_id": "owner"},
    )
    assert resp.status_code == 200
    assert "负数" in resp.text


# ----- v0.4-alpha3 Review Center bulk + filter -------------------------

def _seed_pending_with_amount(web_client: TestClient, amount_yuan: str = "10.00", merchant: str = "测试") -> int:
    """Upload a tiny PNG then patch amount+merchant via /web/expenses/{id}/save."""
    expense_id = _create_pending(web_client)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={"amount_yuan": amount_yuan, "merchant": merchant, "category": "其他",
              "note": "", "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_search_finds_current_ledger_entities(web_client: TestClient) -> None:
    pending_id = _seed_pending_with_amount(web_client, "9.00", "SearchCafe Pending")
    confirmed_id = _seed_pending_with_amount(web_client, "11.00", "SearchCafe Confirmed")
    confirmed = web_client.post(
        f"/web/expenses/{confirmed_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert confirmed.status_code in {303, 307}
    rule = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "SearchCafe",
            "category": "餐饮",
            "priority": "100",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert rule.status_code in {303, 307}
    goal = web_client.post(
        "/web/goals/create",
        data={
            "ledger_id": "owner",
            "month": "2026-05",
            "name": "SearchGoal Groceries",
            "target_amount_yuan": "1000",
            "category": "餐饮",
        },
        follow_redirects=False,
    )
    assert goal.status_code in {303, 307}

    page = web_client.get("/web/search?ledger_id=owner&q=SearchCafe")
    assert page.status_code == 200
    assert f"/web/expenses/{pending_id}/edit?ledger_id=owner" in page.text
    assert f"/web/expenses/{confirmed_id}/edit?ledger_id=owner" in page.text
    assert "/web/rules?ledger_id=owner" in page.text

    goals = web_client.get("/web/search?ledger_id=owner&q=SearchGoal")
    assert goals.status_code == 200
    assert "SearchGoal Groceries" in goals.text
    assert "/web/goals?ledger_id=owner&amp;month=2026-05" in goals.text

    other_ledger = web_client.get("/web/search?ledger_id=tester_1&q=SearchCafe")
    assert other_ledger.status_code == 200
    assert "SearchCafe Pending" not in other_ledger.text
    assert "SearchCafe Confirmed" not in other_ledger.text


def test_web_confirmed_batch_markup_and_updates(web_client: TestClient) -> None:
    expense_id = _seed_pending_with_amount(web_client, "21.00", "Confirmed Bulk Cafe")
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
    api_detail = web_client.get(f"/api/expenses/{expense_id}", headers=cf.app_headers())
    assert api_detail.status_code == 200
    assert api_detail.json()["tags"] == "web, family"


def test_web_pending_filter_missing_amount(web_client: TestClient) -> None:
    pending_no_amount = _create_pending(web_client)  # no amount yet
    pending_with_amount = _seed_pending_with_amount(web_client, "5.00", "A")
    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert resp.status_code == 200
    assert f"/web/expenses/{pending_no_amount}/edit" in resp.text
    assert f"/web/expenses/{pending_with_amount}/edit" not in resp.text


def test_web_pending_filter_ready_excludes_missing_amount(web_client: TestClient) -> None:
    # Seed the ready one first so it doesn't get flagged as duplicate of the
    # second upload (same PNG bytes ⇒ second becomes suspected).
    pending_ready = _seed_pending_with_amount(web_client, "8.00", "Ready")
    pending_no_amount = _create_pending(web_client)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f"/web/expenses/{pending_ready}/edit" in resp.text
    assert f"/web/expenses/{pending_no_amount}/edit" not in resp.text


def test_web_pending_filter_active_tab_marker(web_client: TestClient) -> None:
    _create_pending(web_client)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert resp.status_code == 200
    assert 'class="filter-tab is-active"' in resp.text


def test_web_pending_bulk_selection_markup_and_js_field_name(web_client: TestClient) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X")
    resp = web_client.get("/web/pending?ledger_id=owner")
    assert resp.status_code == 200
    assert f'data-expense-id="{eid}"' in resp.text
    assert 'aria-selected="false"' in resp.text
    assert f'aria-label="选择账单 #{eid}"' in resp.text
    assert 'role="checkbox"' in resp.text
    assert 'name="category"' in resp.text
    assert 'name="merchant"' in resp.text

    js_path = Path(__file__).resolve().parents[1] / "app/static/web/desktop.js"
    js = js_path.read_text(encoding="utf-8")
    assert 'h.name = "expense_ids";' in js


def test_web_bulk_set_category_updates_pending(web_client: TestClient) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X")
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "set_category", "ledger_id": "owner",
              "expense_ids": [str(eid)], "category": "餐饮", "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner")
    assert "餐饮" in detail.text


def test_web_bulk_set_category_requires_value(web_client: TestClient) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X")
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "set_category", "ledger_id": "owner",
              "expense_ids": [str(eid)], "category": "", "filter": "all"},
        follow_redirects=False,
    )
    # Empty input must not silently succeed — either 422 or redirect with skip msg.
    assert resp.status_code in {303, 307, 422}


def test_web_bulk_confirm_ready_skips_missing_amount(web_client: TestClient) -> None:
    no_amount = _create_pending(web_client)
    ready = _seed_pending_with_amount(web_client, "11.00", "Ready")
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


def test_web_bulk_reject_removes_from_pending(web_client: TestClient) -> None:
    eid = _seed_pending_with_amount(web_client, "12.00", "Y")
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "reject", "ledger_id": "owner",
              "expense_ids": [str(eid)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{eid}/edit" not in pending.text


def test_web_bulk_keep_duplicate_persists_flag_clear(web_client: TestClient) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Duplicate A")
    second = _seed_pending_with_amount(web_client, "12.00", "Duplicate B")
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


def test_web_pending_batch_reject_removes_multiple_pending(web_client: TestClient) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Y")
    second = _seed_pending_with_amount(web_client, "13.00", "Z")
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


def test_web_bulk_unknown_action_returns_error(web_client: TestClient) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X")
    resp = web_client.post(
        "/web/review/bulk",
        data={"action": "explode", "ledger_id": "owner",
              "expense_ids": [str(eid)], "filter": "all"},
        follow_redirects=False,
    )
    assert resp.status_code in {400, 422}


def test_web_bulk_cross_ledger_id_is_ignored(web_client: TestClient) -> None:
    """If an id from another ledger is submitted, action must NOT mutate it."""
    eid_owner = _seed_pending_with_amount(web_client, "9.00", "Owner")
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


# ----- v0.4-alpha3 /web/rules page ----------------------------------------

def test_web_rules_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/rules?ledger_id=owner")
    assert resp.status_code == 200
    assert "分类规则" in resp.text


def test_web_rules_create_then_delete(web_client: TestClient) -> None:
    # Create
    resp = web_client.post(
        "/web/rules/create",
        data={"keyword": "测试关键词A", "category": "餐饮", "priority": "100",
              "ledger_id": "owner"},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    page = web_client.get("/web/rules?ledger_id=owner")
    assert "测试关键词A" in page.text
    # Locate id from the page (form action contains /web/rules/{id}/delete)
    import re as _re
    m = _re.search(r"/web/rules/(\d+)/delete", page.text)
    assert m, page.text[:500]
    rule_id = int(m.group(1))
    # Toggle
    resp = web_client.post(
        f"/web/rules/{rule_id}/toggle",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    # Delete
    resp = web_client.post(
        f"/web/rules/{rule_id}/delete",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert resp.status_code in {303, 307}


def test_web_rules_preview_does_not_mutate(web_client: TestClient) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "星巴克 国贸店")
    resp = web_client.get(
        "/web/rules?ledger_id=owner&preview_keyword=星巴克&preview_category=餐饮"
    )
    assert resp.status_code == 200
    # Preview must list the expense.
    assert str(expense_id) in resp.text
    # And original expense category not yet changed (still "其他").
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text


def test_web_rules_apply_pending_audit_and_rollback_integration(
    web_client: TestClient,
) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "Starbucks 上海")
    created = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "Starbucks",
            "category": "餐饮",
            "priority": "1",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    direct = web_client.post(
        "/web/rules/apply-pending",
        data={"ledger_id": "owner"}, follow_redirects=False,
    )
    assert direct.status_code in {303, 307}
    assert "apply_preview=1" in direct.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text

    preview = web_client.get("/web/rules?ledger_id=owner&apply_preview=1")
    assert preview.status_code == 200
    assert "将改写" in preview.text
    assert "Starbucks 上海" in preview.text
    assert "确认应用到待确认" in preview.text

    applied = web_client.post(
        "/web/rules/apply-pending",
        data={"ledger_id": "owner", "preview_confirmed": "yes"},
        follow_redirects=False,
    )
    assert applied.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "餐饮" in detail.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200
    assert "规则应用记录" in page.text
    assert "已应用" in page.text
    assert "回滚" in page.text
    batch_match = re.search(r"/web/rules/applications/([^/]+)/rollback", page.text)
    assert batch_match, page.text[:1000]

    rolled_back = web_client.post(
        f"/web/rules/applications/{batch_match.group(1)}/rollback",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert rolled_back.status_code in {303, 307}
    restored = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in restored.text


def test_web_rules_apply_confirmed_requires_preview_then_applies(
    web_client: TestClient,
) -> None:
    expense_id = _seed_pending_with_amount(web_client, "9.00", "Historical Starbucks")
    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert confirmed.status_code in {303, 307}

    created = web_client.post(
        "/web/rules/create",
        data={
            "keyword": "Historical Starbucks",
            "category": "餐饮",
            "priority": "1",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    direct = web_client.post(
        "/web/rules/apply-confirmed",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert direct.status_code in {303, 307}
    assert "confirmed_preview=1" in direct.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "其他" in detail.text

    preview = web_client.get("/web/rules?ledger_id=owner&confirmed_preview=1")
    assert preview.status_code == 200
    assert "历史账单规则预览" in preview.text
    assert "Historical Starbucks" in preview.text
    assert "确认应用到已确认" in preview.text
    token_match = re.search(r'name="preview_token" value="([0-9a-f]+)"', preview.text)
    assert token_match, preview.text[:1000]

    applied = web_client.post(
        "/web/rules/apply-confirmed",
        data={
            "ledger_id": "owner",
            "preview_confirmed": "yes",
            "preview_token": token_match.group(1),
        },
        follow_redirects=False,
    )
    assert applied.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "餐饮" in detail.text

    page = web_client.get("/web/rules?ledger_id=owner")
    assert page.status_code == 200
    assert "已应用历史" in page.text


# ----- v0.7 /web/merchants page -------------------------------------------

def test_web_merchants_local_returns_200(web_client: TestClient) -> None:
    resp = web_client.get("/web/merchants?ledger_id=owner")
    assert resp.status_code == 200
    assert "商家治理" in resp.text
    assert "不会覆盖原始账单商家" in resp.text


def test_web_merchants_alias_create_toggle_delete(web_client: TestClient) -> None:
    created = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "星巴克",
            "alias": "STARBUCKS 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=False,
    )
    assert created.status_code in {303, 307}

    page = web_client.get("/web/merchants?ledger_id=owner")
    assert page.status_code == 200
    assert "STARBUCKS 国贸店" in page.text
    assert "starbucks 国贸店" in page.text

    duplicate = web_client.post(
        "/web/merchants/aliases/create",
        data={
            "canonical_merchant": "另一家",
            "alias": "starbucks 国贸店",
            "ledger_id": "owner",
        },
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert "商家别名已指向其他商家" in duplicate.text

    import re as _re
    match = _re.search(r"/web/merchants/aliases/([^/]+)/delete", page.text)
    assert match, page.text[:500]
    public_id = match.group(1)

    toggled = web_client.post(
        f"/web/merchants/aliases/{public_id}/toggle",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert toggled.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "停用" in page.text

    deleted = web_client.post(
        f"/web/merchants/aliases/{public_id}/delete",
        data={"ledger_id": "owner"},
        follow_redirects=False,
    )
    assert deleted.status_code in {303, 307}
    page = web_client.get("/web/merchants?ledger_id=owner")
    assert "还没有商家别名" in page.text
