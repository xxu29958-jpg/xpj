"""Confirmed-ledger, partial-response, and bulk-row-structure Web contracts."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from _web_bulk_test_support import (
    bulk_snapshot_fields as _bulk_snapshot_fields,
)
from _web_bulk_test_support import (
    create_pending as _create_pending,
)
from _web_bulk_test_support import (
    row_version as _row_version,
)
from _web_bulk_test_support import (
    seed_pending_with_amount as _seed_pending_with_amount,
)
from api_contract_helpers import web_confirm_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Account, Device, Expense


class _RowLinkNestingProbe(HTMLParser):
    """Flags interactive elements nested inside a row navigation anchor.

    行结构合同 (#218, S4-R1 复核): 两个批量页的选择控件都与整行链接互为
    兄弟节点 (pending 的 .exp-row-selector / confirmed 的 .timeline-row 选择
    槽); 行链接 (a.exp-row-detail / a.timeline-row-detail) 内不允许出现任何
    交互标签 (<a>/<button>/<input>/<select>/<textarea>) — 嵌套交互标签是
    无效 HTML, 且会回到 C5a 的穿透回归 (点击勾选控件同时触发整行跳转)。
    pending 的原生 checkbox 同样在行链接外；其兄弟位与无 JS 表单
    关联由 test_web_inbox_rebuild 的断言钉死。
    """

    _INTERACTIVE = {"a", "button", "input", "select", "textarea"}
    _VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, row_link_class: str) -> None:
        super().__init__()
        self._row_link_class = row_link_class
        self._open_link_depth = 0
        self.row_links = 0
        self.nested_interactive: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if self._open_link_depth == 0 and tag == "a" and self._row_link_class in classes:
            self._open_link_depth = 1
            self.row_links += 1
            return
        if self._open_link_depth > 0:
            if tag in self._INTERACTIVE:
                self.nested_interactive.append(tag)
            if tag not in self._VOID:
                self._open_link_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._open_link_depth > 0 and tag not in self._VOID:
            self._open_link_depth -= 1


def test_web_bulk_rows_do_not_nest_interactive_elements(web_client: TestClient, *, identity) -> None:
    """行链接嵌套合同: 两个批量页的行导航锚点 (pending 的 a.exp-row-detail,
    confirmed 的 a.timeline-row-detail) 内都不允许出现任何交互标签
    (<a>/<button>/<input>/<select>/<textarea>)。"""
    confirmed_id = _seed_pending_with_amount(web_client, "9.00", "Nesting Confirmed", identity=identity)
    confirmed = web_confirm_expense(web_client, confirmed_id, identity=identity, follow_redirects=False)
    assert confirmed.status_code in {303, 307}
    _seed_pending_with_amount(web_client, "10.00", "Nesting Pending", identity=identity)

    pages = (
        (web_client.get("/web/pending?ledger_id=owner"), "exp-row-detail"),
        (web_client.get("/web/confirmed?ledger_id=owner"), "timeline-row-detail"),
    )
    for resp, row_link_class in pages:
        assert resp.status_code == 200
        probe = _RowLinkNestingProbe(row_link_class)
        probe.feed(resp.text)
        probe.close()
        assert probe.row_links > 0, f"no {row_link_class} rows rendered"
        assert probe.nested_interactive == []


def _confirmed_expense_with_web_actor(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> int:
    expense_id = _seed_pending_with_amount(web_client, "21.00", "Confirmed Bulk Cafe", identity=identity)
    confirmed = web_confirm_expense(web_client, expense_id, identity=identity, follow_redirects=False)
    assert confirmed.status_code in {303, 307}
    with SessionLocal() as db:
        actor_account_id = db.scalar(select(Account.id).where(Account.display_name == "我"))
        actor_device_id = db.scalar(
            select(Device.id).where(Device.device_name == "pytest-android")
        )
        assert actor_account_id is not None and actor_device_id is not None
    monkeypatch.setattr(
        "app.routes.web_confirmed_batch.resolve_web_actor",
        lambda *_args: (actor_account_id, actor_device_id),
    )
    return expense_id


def test_web_confirmed_batch_markup(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id = _confirmed_expense_with_web_actor(
        web_client,
        monkeypatch,
        identity=identity,
    )

    page = web_client.get("/web/confirmed?ledger_id=owner")
    assert page.status_code == 200
    assert 'action="/web/confirmed/batch-update"' in page.text
    assert f'data-id="{expense_id}"' in page.text
    assert 'data-row-version="' in page.text
    assert (
        '<input class="checkbox" id="check-all" type="checkbox" '
        'aria-label="选择本页全部账单" hidden>'
    ) in page.text
    assert 'name="reason"' in page.text
    assert 'name="idempotency_key"' in page.text
    assert 'type="checkbox"' in page.text
    assert 'role="checkbox"' not in page.text
    # 行结构已按 #218 拆开:checkbox(.lrow-sel) 与整行链接(a.timeline-row-detail)
    # 是兄弟节点,行容器 .timeline-row 不再是锚点。
    assert "timeline-row-detail" in page.text
    assert f'aria-label="选择账单 #{expense_id}"' not in page.text
    assert "选择账单：Confirmed Bulk Cafe" in page.text
    assert "批量改分类" in page.text
    assert "批量改标签" in page.text
    assert ('<button class="dt-btn" type="button" data-bulk-clear>取消选择</button>') in page.text


def test_web_confirmed_batch_updates_and_records_actor(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id = _confirmed_expense_with_web_actor(
        web_client,
        monkeypatch,
        identity=identity,
    )
    token = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["row_version"]

    category_resp = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": [str(expense_id)],
            "expected_row_version": [token],
            "category": "Batch Web Cat",
            "reason": "统一整理分类",
            "idempotency_key": "web-batch-category",
            "page": "2",
        },
        follow_redirects=False,
    )
    assert category_resp.status_code in {303, 307}
    assert "page=2" in category_resp.headers["location"]
    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert "Batch Web Cat" in detail.text
    token = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["row_version"]

    tags_resp = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_tags",
            "ledger_id": "owner",
            "expense_ids": [str(expense_id)],
            "expected_row_version": [token],
            "tags": "web, family, web",
            "reason": "统一整理标签",
            "idempotency_key": "web-batch-tags",
        },
        follow_redirects=False,
    )
    assert tags_resp.status_code in {303, 307}
    api_detail = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers)
    assert api_detail.status_code == 200
    assert api_detail.json()["tags"] == "web, family"
    timeline = web_client.get(
        f"/api/expenses/{expense_id}/revisions",
        headers=identity.app_headers,
    )
    assert timeline.status_code == 200, timeline.text
    batch_revisions = [
        revision
        for revision in timeline.json()["items"]
        if revision["reason"] in {"统一整理分类", "统一整理标签"}
    ]
    assert len(batch_revisions) == 2
    assert {revision["actor_account_name"] for revision in batch_revisions} == {"我"}
    assert {revision["actor_device_name"] for revision in batch_revisions} == {
        "pytest-android"
    }


def test_web_confirmed_batch_stale_token_redirects_without_partial_update(web_client: TestClient, *, identity) -> None:
    first_id = _seed_pending_with_amount(web_client, "21.00", "Bulk Stale A", identity=identity)
    second_id = _seed_pending_with_amount(web_client, "22.00", "Bulk Stale B", identity=identity)
    for expense_id in (first_id, second_id):
        confirmed = web_confirm_expense(web_client, expense_id, identity=identity, follow_redirects=False)
        assert confirmed.status_code in {303, 307}

    first_before = web_client.get(f"/api/expenses/{first_id}", headers=identity.app_headers).json()
    second_before = web_client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    changed = web_client.post(
        f"/api/expenses/{first_id}/corrections",
        headers={
            **identity.app_headers,
            "Idempotency-Key": f"batch-stale-{first_id}",
        },
        json={
            "expected_row_version": first_before["row_version"],
            "category": "Intervening",
            "reason": "制造真实并发更正",
        },
    )
    assert changed.status_code == 201, changed.text

    response = web_client.post(
        "/web/confirmed/batch-update",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": [str(first_id), str(second_id)],
            "expected_row_version": [first_before["row_version"], second_before["row_version"]],
            "category": "Should Not Land",
            "reason": "批量分类",
            "idempotency_key": "web-batch-stale",
        },
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert "账单已在其它端被修改" in response.text

    first_after = web_client.get(f"/api/expenses/{first_id}", headers=identity.app_headers).json()
    second_after = web_client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert first_after["category"] == "Intervening"
    assert second_after["category"] == second_before["category"]


def test_web_bulk_confirm_ready_fragment_returns_actioned_ids(web_client: TestClient, *, identity) -> None:
    """fragment=1 confirm_ready answers JSON {removed_ids, message, flash_type}
    naming ONLY the rows that actually left the queue — the missing-amount row is
    skipped, stays pending, and is NOT in removed_ids (the client must not assume
    every selected row succeeded)."""
    no_amount = _create_pending(web_client, identity=identity)
    # Seed the ready row via direct insert: the shared upload helper reuses one
    # fixed PNG payload, so a second upload would be flagged duplicate=suspected
    # and — now that confirm_ready requires the full ready predicate — skipped.
    with SessionLocal() as db:
        ready_expense = Expense(
            tenant_id="owner",
            amount_cents=1100,
            merchant="Ready",
            category="其他",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        db.add(ready_expense)
        db.commit()
        ready = ready_expense.id
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "confirm_ready",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(
                web_client,
                [no_amount, ready],
                identity=identity,
            ),
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["removed_ids"] == [ready]
    assert body["flash_type"] == "success"
    assert "已确认 1 条" in body["message"]
    assert "跳过 1 条" in body["message"]
    redirect = urlsplit(body["redirect_url"])
    assert redirect.path == "/web/pending"
    assert parse_qs(redirect.query)["ledger_id"] == ["owner"]
    assert parse_qs(redirect.query)["filter"] == ["all"]
    assert parse_qs(redirect.query)["flash_type"] == ["success"]
    # Server-side state actually changed: ready confirmed (gone), no-amount stays.
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{ready}/edit" not in pending.text
    assert f"/web/expenses/{no_amount}/edit" in pending.text


def test_web_bulk_confirm_ready_fragment_excludes_cross_ledger(web_client: TestClient, *, identity) -> None:
    """removed_ids must never name a row outside the current ledger — a foreign
    id lands in skipped_reasons, never success_ids, so the client can't be told
    to splice a row it doesn't own."""
    ready = _seed_pending_with_amount(web_client, "11.00", "Ready", identity=identity)
    bogus_id = ready + 99999  # id far outside any existing range
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "confirm_ready",
            "ledger_id": "owner",
            "expense_ids": [str(ready), str(bogus_id)],
            "expected_row_version": [
                str(_row_version(web_client, ready, identity=identity)),
                "1",
            ],
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["removed_ids"] == [ready]
    assert bogus_id not in body["removed_ids"]
    assert "已确认 1 条" in body["message"]
    assert "不属于当前账本" in body["message"]


def test_web_batch_reject_fragment_returns_removed_ids(web_client: TestClient, *, identity) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Y", identity=identity)
    second = _seed_pending_with_amount(web_client, "13.00", "Z", identity=identity)
    resp = web_client.post(
        "/web/pending/batch-reject",
        data={
            "ledger_id": "owner",
            **_bulk_snapshot_fields(
                web_client,
                [first, second],
                identity=identity,
            ),
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["removed_ids"]) == {first, second}
    assert {item["id"] for item in body["undo_items"]} == {first, second}
    assert all(item["expected_row_version"] > 0 for item in body["undo_items"])
    assert body["flash_type"] == "success"
    assert "已忽略 2 条" in body["message"]
    redirect = urlsplit(body["redirect_url"])
    query = parse_qs(redirect.query)
    assert redirect.path == "/web/pending"
    assert query["ledger_id"] == ["owner"]
    assert query["filter"] == ["all"]
    assert query["flash_type"] == ["success"]
    assert set(map(int, query["undo_id"])) == {first, second}
    assert sorted(map(int, query["undo_rv"])) == sorted(item["expected_row_version"] for item in body["undo_items"])
    authoritative = web_client.get(body["redirect_url"])
    assert authoritative.status_code == 200
    assert "收件队列已经清空" in authoritative.text
    assert "撤销 2 条" in authoritative.text
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{first}/edit" not in pending.text
    assert f"/web/expenses/{second}/edit" not in pending.text


def test_web_batch_reject_fragment_no_selection_returns_error_json(
    web_client: TestClient,
) -> None:
    resp = web_client.post(
        "/web/pending/batch-reject",
        data={"ledger_id": "owner", "filter": "all", "fragment": "1"},
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["removed_ids"] == []
    assert body["flash_type"] == "error"
    assert "请先勾选账单" in body["message"]


def test_web_bulk_set_category_ignores_fragment_and_redirects(web_client: TestClient, *, identity) -> None:
    """fragment is honoured ONLY for removal actions — set_category mutates a row
    in place (it stays visible), so it keeps the full-page redirect even with
    fragment=1. Pins the _REMOVAL_ACTIONS gate so an in-place action can never
    claim rows were removed."""
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, [eid], identity=identity),
            "category": "餐饮",
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}  # redirect, NOT a JSON fragment
    assert "removed_ids" not in resp.text  # gate is behaviour-pinned, not just 200-vs-303
    detail = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner")
    assert "餐饮" in detail.text


def test_bulk_bar_js_has_fetch_partial_mechanism() -> None:
    """The /web fetch-JS has no browser test in the suite (like drawer.js), so a
    content-assertion is the regression floor: pin the markers of the fetch+partial
    path so ripping it out (silent regression to full-page reload) reds here."""
    js_path = Path(__file__).resolve().parents[1] / "app/static/web/desktop/bulk-bar.js"
    js = js_path.read_text(encoding="utf-8")
    assert 'body.append("fragment", "1");' in js
    assert "function removalKind" in js
    assert "removed_ids" in js
    assert "undo_items" in js
    assert "/web/pending/batch-undo" in js
    assert "data-native-fallback" in js  # offline → native full-page fallback
