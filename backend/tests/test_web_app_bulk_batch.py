"""Tests for the /web 桌面账本流 UI (v0.4-alpha2 Tri-surface contract)."""

from __future__ import annotations

import re
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
    assert f'data-expense-id="{pending_no_amount}"' in resp.text
    assert f"/web/expenses/{pending_no_amount}/edit" in resp.text
    assert f'data-expense-id="{pending_with_amount}"' not in resp.text


def test_web_pending_filter_ready_excludes_missing_amount(web_client: TestClient, *, identity) -> None:
    # Seed the ready one first so it doesn't get flagged as duplicate of the
    # second upload (same PNG bytes ⇒ second becomes suspected).
    pending_ready = _seed_pending_with_amount(web_client, "8.00", "Ready", identity=identity)
    pending_no_amount = _create_pending(web_client, identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    # Filters govern selectable bill rows; recent task links retain their separate read-only history.
    assert f'data-expense-id="{pending_ready}"' in resp.text
    assert f"/web/expenses/{pending_ready}/edit" in resp.text
    assert f'data-expense-id="{pending_no_amount}"' not in resp.text
    assert f'data-id="{pending_no_amount}"' not in resp.text


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
    assert f'data-expense-id="{noise_id}"' in resp.text
    assert f"/web/expenses/{noise_id}/edit" in resp.text
    assert f'data-expense-id="{usable_id}"' not in resp.text

    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f'data-expense-id="{noise_id}"' not in resp.text
    assert f'data-expense-id="{usable_id}"' in resp.text
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
    assert f'data-expense-id="{none_id}"' in resp.text
    assert f"/web/expenses/{none_id}/edit" in resp.text
    assert f'data-expense-id="{null_id}"' in resp.text
    assert f"/web/expenses/{null_id}/edit" in resp.text
    assert f'data-expense-id="{other_id}"' not in resp.text

    resp = web_client.get("/web/pending?ledger_id=owner&filter=ready")
    assert resp.status_code == 200
    assert f'data-expense-id="{none_id}"' not in resp.text
    assert f'data-expense-id="{null_id}"' not in resp.text
    assert f'data-expense-id="{other_id}"' in resp.text
    assert f"/web/expenses/{other_id}/edit" in resp.text


def test_web_pending_filter_active_tab_marker(web_client: TestClient, *, identity) -> None:
    _create_pending(web_client, identity=identity)
    resp = web_client.get("/web/pending?ledger_id=owner&filter=missing_amount")
    assert resp.status_code == 200
    assert 'class="filter-tab is-active"' in resp.text


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

    mixed_snapshot = web_client.post(
        "/web/review/bulk",
        data={
            "action": "set_category",
            "ledger_id": "owner",
            "expense_ids": [str(eid)],
            "expected_row_version": [str(before["row_version"])],
            "expense_snapshot": f"{eid}:{before['row_version'] + 1}",
            "category": "不应写入",
            "filter": "all",
        },
        follow_redirects=True,
    )
    assert mixed_snapshot.status_code == 200
    assert "页面已过期，请刷新后重新操作" in mixed_snapshot.text

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
@pytest.mark.parametrize("fragment", ["0", "1"])
def test_web_pending_bulk_skips_t1_snapshot_after_t2_change(
    web_client: TestClient,
    *,
    identity,
    operation: str,
    fragment: str,
) -> None:
    completed = _seed_pending_with_amount(web_client, "7.00", "Ready Merchant", identity=identity)
    completed_token = _row_version(web_client, completed, identity=identity)
    eid = _seed_pending_with_amount(
        web_client,
        "19.00",
        "Snapshot Merchant",
        identity=identity,
    )
    # The shared upload fixture uses the same image. Establish independent
    # records before taking T1, so rejecting one does not clear the other's
    # real duplicate relationship as a separate, legitimate revision.
    kept = web_client.post("/web/review/bulk", data={
        "action": "keep_duplicate", "ledger_id": "owner",
        **_bulk_snapshot_fields(web_client, [eid], identity=identity),
    }, follow_redirects=False)
    assert kept.status_code == 303
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
                "expense_snapshot": [f"{completed}:{completed_token}", f"{eid}:{t1_token}"],
                "filter": "all",
                "fragment": fragment,
            },
            follow_redirects=False,
        )
    else:
        response = web_client.post(
            "/web/review/bulk",
            data={
                "action": "set_category" if operation == "metadata" else "confirm_ready",
                "ledger_id": "owner",
                "expense_snapshot": [f"{completed}:{completed_token}", f"{eid}:{t1_token}"],
                "category": "T3 不应覆盖",
                "filter": "all",
                "fragment": fragment,
            },
            follow_redirects=False,
        )

    if operation == "metadata" or fragment == "0":
        assert response.status_code in {303, 307}
        result_url = response.headers["location"]
    else:
        assert response.status_code == 200, response.text
        assert response.json()["removed_ids"] == [completed]
        assert "内容已变化，请打开账单核对后再继续" in response.json()["message"]
        result_url = response.json()["redirect_url"]

    query = parse_qs(urlsplit(result_url).query)
    assert query["remaining"] == [f"{eid}:{t1_token}"]
    assert query["ledger_id"] == ["owner"] and query["filter"] == ["all"]
    if operation == "metadata":
        assert query["bulk_category"] == ["T3 不应覆盖"]
    # Reload reprojects the original failed selection; it neither adopts T2's
    # token nor selects the successful row for a second write.
    for _ in range(2):
        rendered = web_client.get(result_url)
        assert rendered.status_code == 200
        assert "内容已变化，请打开账单核对后再继续" in rendered.text
        selected = re.findall(r'<input\b[^>]*\bname="expense_snapshot"[^>]*\bchecked[^>]*>', rendered.text)
        assert len(selected) == 1 and f'value="{eid}:{t1_token}"' in selected[0]

    after = web_client.get(
        f"/api/expenses/{eid}",
        headers=identity.app_headers,
    ).json()
    assert after["status"] == "pending"
    assert after["amount_cents"] == t2["amount_cents"] == 4400
    assert after["category"] == t2["category"] == "T2 保留分类"
    assert after["row_version"] == t2["row_version"]
    accepted = web_client.get(f"/api/expenses/{completed}", headers=identity.app_headers).json()
    assert accepted["amount_cents"] == 700 and accepted["row_version"] == completed_token + 1
    assert accepted["status"] == {"metadata": "pending", "confirm": "confirmed", "reject": "rejected"}[operation]


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
    assert f'data-expense-id="{ready}"' not in pending.text
    # The no-amount one stays pending.
    assert f'data-expense-id="{no_amount}"' in pending.text
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
    assert f'data-expense-id="{eid}"' not in pending.text


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
    assert f'data-expense-id="{first}"' not in pending.text
    assert f'data-expense-id="{second}"' not in pending.text


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
    assert f'data-expense-id="{eid_owner}"' in pending.text
    assert f"/web/expenses/{eid_owner}/edit" in pending.text
