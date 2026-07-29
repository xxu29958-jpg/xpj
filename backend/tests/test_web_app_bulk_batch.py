"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

from pathlib import Path

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
from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense


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


def test_web_pending_merchant_caliber_matches_data_quality(web_client: TestClient, *, identity) -> None:
    """PR #230: the web missing_merchant / ready filters share the data-quality
    merchant-usability caliber — OCR time noise counts as a missing merchant,
    not just NULL/blank."""
    with SessionLocal() as db:
        noise = Expense(
            tenant_id="owner",
            amount_cents=100,
            merchant="12:34",
            category="餐饮",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        usable = Expense(
            tenant_id="owner",
            amount_cents=200,
            merchant="星巴克",
            category="餐饮",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        db.add_all([noise, usable])
        db.commit()
        noise_id, usable_id = noise.id, usable.id

    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_merchant")
    assert resp.status_code == 200
    assert f"/web/expenses/{noise_id}/edit" in resp.text
    assert f"/web/expenses/{usable_id}/edit" not in resp.text

    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f"/web/expenses/{noise_id}/edit" not in resp.text
    assert f"/web/expenses/{usable_id}/edit" in resp.text


def test_web_pending_category_caliber_matches_data_quality(web_client: TestClient, *, identity) -> None:
    """PR #230: the web missing_category / ready filters share the data-quality
    uncategorized token set — literal none/null categories count as missing,
    while 其他 remains a valid user-chosen category."""
    with SessionLocal() as db:
        token_none = Expense(
            tenant_id="owner",
            amount_cents=100,
            merchant="商家甲",
            category="none",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        token_null = Expense(
            tenant_id="owner",
            amount_cents=200,
            merchant="商家乙",
            category="NULL",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        other = Expense(
            tenant_id="owner",
            amount_cents=300,
            merchant="商家丙",
            category="其他",
            source="pytest",
            status="pending",
            duplicate_status="none",
        )
        db.add_all([token_none, token_null, other])
        db.commit()
        none_id, null_id, other_id = token_none.id, token_null.id, other.id

    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_category")
    assert resp.status_code == 200
    assert f"/web/expenses/{none_id}/edit" in resp.text
    assert f"/web/expenses/{null_id}/edit" in resp.text
    assert f"/web/expenses/{other_id}/edit" not in resp.text

    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f"/web/expenses/{none_id}/edit" not in resp.text
    assert f"/web/expenses/{null_id}/edit" not in resp.text
    assert f"/web/expenses/{other_id}/edit" in resp.text


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
    # 218-D S4-R1 行结构 (#218 同构): 勾选控件是容器内兄弟槽的 div[role=checkbox],
    # 行链接 a.exp-row-detail 子树零交互控件; input[type=checkbox] 随旧栈退役。
    assert 'aria-selected="false"' in resp.text
    assert ('<button class="product-button" type="button" data-bulk-clear>取消选择</button>') in resp.text
    assert f'aria-label="选择账单 #{eid}"' in resp.text
    assert 'role="checkbox"' in resp.text
    assert 'type="checkbox"' not in resp.text
    assert 'data-row-version="' in resp.text
    assert "exp-row-detail" in resp.text
    assert 'name="category"' in resp.text
    assert 'name="merchant"' in resp.text

    js_path = Path(__file__).resolve().parents[1] / "app/static/web/desktop/bulk-bar.js"
    js = js_path.read_text(encoding="utf-8")
    assert 'h.name = "expense_ids";' in js
    assert 'token.name = "expected_row_version";' in js
    # 快照 token 恒 emitted(不再 if (entry.rowVersion) 条件跳过)——缺失即 409 fail-closed。
    assert "token.value = entry.rowVersion;" in js
    assert "if (entry.rowVersion)" not in js
    # 双模式 checkbox: 新页 div.checked class / 旧页 input :checked。
    assert '".row-check:checked, .row-check.checked"' in js
    assert "isNativeBox" in js
    assert 'classList.toggle("checked", on);' in js
    assert 'row.setAttribute("aria-disabled", "true");' in js
    assert 'row.setAttribute("tabindex", "-1");' in js
    assert "setBatchNavigationMode(entries.length > 0);" in js
    assert "e.stopPropagation();" in js  # 吞事件兜底, 勾选不穿透开抽屉 (C5a)
    assert "e.preventDefault();" in js

    drawer_js = js_path.with_name("drawer.js").read_text(encoding="utf-8")
    hotkeys_js = js_path.with_name("review-hotkeys.js").read_text(encoding="utf-8")
    # 批选模式(非空选择)挂起行导航:drawer 点击 + 程序化 open 都要尊重 aria-disabled。
    assert 'row.getAttribute("aria-disabled") === "true"' in drawer_js
    assert 'getAttribute("aria-disabled") !== "true"' in hotkeys_js
    # S4-R2: J/K 当前行同步容器 is-current 高亮 (与 drawer 同族), 键盘流不盲。
    assert 'classList.toggle("is-current", r === row);' in hotkeys_js
    inbox_css = js_path.parents[1] / "product" / "domains" / "inbox.css"
    assert inbox_css.read_text(encoding="utf-8").count(".exp-row.is-current") >= 1


def test_web_bulk_set_category_updates_pending(web_client: TestClient, *, identity) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    before_token = _row_version(web_client, eid, identity=identity)
    resp = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            # 重复 id 会去重,整批只应用一次。
            "expense_ids": [str(eid), str(eid)],
            "expected_row_version": [str(before_token), str(before_token)],
            "category": "餐饮",
            "filter": "all",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}
    detail = web_client.get(f"/web/expenses/{eid}/edit?ledger_id=owner")
    assert "餐饮" in detail.text
    assert _row_version(web_client, eid, identity=identity) == before_token + 1


def test_web_pending_bulk_fails_closed_on_invalid_payloads(
    web_client: TestClient,
    *,
    identity,
) -> None:
    eid = _seed_pending_with_amount(web_client, "9.00", "X", identity=identity)
    before = web_client.get(
        f"/api/expenses/{eid}",
        headers=identity.app_headers,
    ).json()

    missing_token = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": [str(eid)],
            "category": "不应写入",
            "filter": "all",
        },
        follow_redirects=True,
    )
    assert missing_token.status_code == 200
    assert "页面已过期，请刷新后重新操作" in missing_token.text

    malformed_token = web_client.post(
        "/web/review/bulk",
        data={
            "action": "confirm_ready",
            "ledger_id": "owner",
            "expense_ids": [str(eid)],
            "expected_row_version": ["not-a-token"],
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert malformed_token.status_code == 409
    assert malformed_token.json()["removed_ids"] == []
    assert "页面已过期" in malformed_token.json()["message"]

    empty_category = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, [eid], identity=identity),
            "category": "",
            "filter": "all",
        },
        follow_redirects=False,
    )
    # Empty input must not silently succeed — either 422 or redirect with skip msg.
    assert empty_category.status_code in {303, 307, 422}

    after = web_client.get(
        f"/api/expenses/{eid}",
        headers=identity.app_headers,
    ).json()
    assert after["status"] == before["status"]
    assert after["category"] == before["category"]
    assert after["amount_cents"] == before["amount_cents"]


@pytest.mark.parametrize("operation", ["metadata", "confirm", "reject"])
def test_web_pending_bulk_skips_t1_snapshot_after_t2_change(
    web_client: TestClient,
    *,
    identity,
    operation: str,
) -> None:
    eid = _seed_pending_with_amount(
        web_client,
        "19.00",
        "Snapshot Merchant",
        identity=identity,
    )
    t1_token = _row_version(web_client, eid, identity=identity)

    changed = web_save_expense(
        web_client,
        eid,
        identity=identity,
        data={
            "amount_yuan": "44.00",
            "merchant": "Snapshot Merchant",
            "category": "T2 保留分类",
            "ledger_id": "owner",
        },
    )
    assert changed.status_code in {303, 307}, changed.text
    t2 = web_client.get(
        f"/api/expenses/{eid}",
        headers=identity.app_headers,
    ).json()
    assert t2["row_version"] > t1_token

    if operation == "reject":
        response = web_client.post(
            "/web/pending/batch-reject",
            data={
                "ledger_id": "owner",
                "expense_ids": [str(eid)],
                "expected_row_version": [str(t1_token)],
                "filter": "all",
                "fragment": "1",
            },
            follow_redirects=False,
        )
    else:
        response = web_client.post(
            "/web/review/bulk",
            data={
                "action": "set_category" if operation == "metadata" else "confirm_ready",
                "ledger_id": "owner",
                "expense_ids": [str(eid)],
                "expected_row_version": [str(t1_token)],
                "category": "T3 不应覆盖",
                "filter": "all",
                "fragment": "1",
            },
            follow_redirects=False,
        )

    if operation == "metadata":
        assert response.status_code in {303, 307}
        rendered = web_client.get(response.headers["location"])
        assert "页面内容已变化，请刷新后重新选择" in rendered.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["removed_ids"] == []
        assert "页面内容已变化，请刷新后重新选择" in response.json()["message"]

    after = web_client.get(
        f"/api/expenses/{eid}",
        headers=identity.app_headers,
    ).json()
    assert after["status"] == "pending"
    assert after["amount_cents"] == t2["amount_cents"] == 4400
    assert after["category"] == t2["category"] == "T2 保留分类"
    assert after["row_version"] == t2["row_version"]


def test_web_bulk_confirm_ready_skips_missing_amount(web_client: TestClient, *, identity) -> None:
    no_amount = _create_pending(web_client, identity=identity)
    ready = _seed_pending_with_amount(web_client, "11.00", "Ready", identity=identity)
    # Full ready caliber needs a real category and a clean duplicate flag —
    # the second same-bytes upload gets flagged suspected, and both the
    # 未分类 default and suspected rows are correctly skipped since round 7.
    with SessionLocal() as db:
        row = db.get(Expense, ready)
        assert row is not None
        row.category = "餐饮"
        row.duplicate_status = "none"
        db.commit()
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
        },
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
        data={
            "action": "reject",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, [eid], identity=identity),
            "filter": "all",
        },
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
        data={
            "action": "keep_duplicate",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, [second], identity=identity),
            "filter": "all",
        },
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
        data={
            "ledger_id": "owner",
            **_bulk_snapshot_fields(
                web_client,
                [first, second],
                identity=identity,
            ),
            "filter": "all",
        },
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
        data={
            "action": "explode",
            "ledger_id": "owner",
            **_bulk_snapshot_fields(web_client, [eid], identity=identity),
            "filter": "all",
        },
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
        data={
            "action": "reject",
            "ledger_id": "owner",
            "expense_ids": [str(bogus_id)],
            "expected_row_version": ["1"],
            "filter": "all",
        },
        follow_redirects=False,
    )
    # Should redirect (no crash, no mutation).
    assert resp.status_code in {303, 307}
    # Owner ledger still has its expense.
    pending = web_client.get("/web/pending?ledger_id=owner")
    assert f"/web/expenses/{eid_owner}/edit" in pending.text
