from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api_contract_helpers import web_confirm_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import Expense, LedgerAuditLog, LedgerMember
from app.routes._web_expense_rows import item_replace_payload
from app.routes.web_app import _require_local as _web_require_local
from app.schemas import (
    ExpenseItemReplaceRequest,
    ExpenseItemRequest,
    ExpenseSplitReplaceRequest,
    ExpenseSplitRequest,
)
from app.services.expense_split_service import replace_expense_splits
from app.services.receipt_item_service import replace_expense_items
from app.services.time_service import now_utc


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _seed_pending_expense(
    *,
    amount_cents: int = 1234,
    currency_code: str = "CNY",
    source: str = "manual",
) -> int:
    with SessionLocal() as db:
        now = now_utc()
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            home_currency_code=currency_code,
            original_currency_code=currency_code,
            original_amount_minor=amount_cents,
            merchant="家庭超市",
            category="生活",
            note="周末采购",
            source=source,
            image_path=None,
            thumbnail_path=None,
            image_hash=None,
            raw_text="",
            confidence=None,
            status="pending",
            expense_time=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.commit()
        return expense.id


def _owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return member.id


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_web_expense_edit_routes_have_single_owner() -> None:
    expected = {
        ("GET", "/web/expenses/{expense_id}/edit"): "app.routes.web_expense_edit",
        ("POST", "/web/expenses/{expense_id}/save"): "app.routes.web_expense_edit",
        ("POST", "/web/expenses/{expense_id}/confirm"): "app.routes.web_expense_edit",
        ("POST", "/web/expenses/{expense_id}/reject"): "app.routes.web_expense_edit",
        ("POST", "/web/expenses/{expense_id}/items/save"): "app.routes.web_expense_items",
        ("POST", "/web/expenses/{expense_id}/splits/save"): "app.routes.web_expense_splits",
    }
    seen: dict[tuple[str, str], list[str]] = {key: [] for key in expected}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        endpoint = getattr(route, "endpoint", None)
        for key in expected:
            method, target_path = key
            if path == target_path and method in methods:
                seen[key].append(getattr(endpoint, "__module__", ""))

    for key, modules in seen.items():
        assert modules == [expected[key]], f"{key} resolved to {modules}"


def _seed_detail_rows(expense_id: int) -> None:
    member_id = _owner_member_id()
    with SessionLocal() as db:
        expected_row_version = db.scalar(
            select(Expense.row_version).where(Expense.id == expense_id)
        )
        assert expected_row_version is not None
        replace_expense_items(
            db,
            expense_id,
            "owner",
            ExpenseItemReplaceRequest(
                expected_row_version=expected_row_version,
                items=[
                    ExpenseItemRequest(
                        name="牛奶",
                        quantity_text="1盒",
                        amount_cents=580,
                        category="生活",
                    )
                ]
            ),
        )
    with SessionLocal() as db:
        expected_row_version = db.scalar(
            select(Expense.row_version).where(Expense.id == expense_id)
        )
        assert expected_row_version is not None
        replace_expense_splits(
            db,
            expense_id,
            "owner",
            ExpenseSplitReplaceRequest(
                expected_row_version=expected_row_version,
                splits=[ExpenseSplitRequest(member_id=member_id, amount_cents=1234, note="我先记")]
            ),
            actor_account_id=None,
        )


def test_web_edit_can_replace_receipt_items_and_family_splits(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense()
    member_id = _owner_member_id()
    item_snapshot = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert item_snapshot.status_code == 200, item_snapshot.json()

    items = web_client.post(
        f"/web/expenses/{expense_id}/items/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": item_snapshot.json()["row_version"],
            "item_name": ["牛奶", "面包", ""],
            "item_quantity": ["1盒", "2个", ""],
            "item_unit_price_yuan": ["", "3.25", ""],
            "item_amount_yuan": ["5.80", "6.50", ""],
            "item_category": ["生活", "餐饮", ""],
        },
        follow_redirects=False,
    )
    assert items.status_code in {303, 307}, items.text

    split_snapshot = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    )
    assert split_snapshot.status_code == 200, split_snapshot.json()
    splits = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": split_snapshot.json()["row_version"],
            "split_member_id": [str(member_id), ""],
            "split_amount_yuan": ["12.34", ""],
            "split_note": ["我先记", ""],
        },
        follow_redirects=False,
    )
    assert splits.status_code in {303, 307}, splits.text

    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200
    assert "牛奶" in detail.text
    assert "面包" in detail.text
    assert "家庭拆账" in detail.text
    assert "我先记" in detail.text
    assert detail.text.count('name="csrf_token"') >= 4

    api_items = web_client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert api_items.status_code == 200, api_items.json()
    assert api_items.json()["items_total_amount_cents"] == 1230
    assert [item["name"] for item in api_items.json()["items"]] == ["牛奶", "面包"]

    api_splits = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    assert api_splits.status_code == 200, api_splits.json()
    assert api_splits.json()["splits_total_amount_cents"] == 1234
    with SessionLocal() as db:
        audit = db.scalar(
            select(LedgerAuditLog)
            .where(LedgerAuditLog.ledger_id == "owner")
            .where(LedgerAuditLog.action == "expense_splits_replaced")
            .order_by(LedgerAuditLog.id.desc())
            .limit(1)
        )
        assert audit is not None
        assert audit.actor_account_id is not None


def test_web_item_and_split_validation_retains_rows_and_anchors_errors(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _seed_pending_expense()
    snapshot = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    parsed = item_replace_payload(
        currency_code="CNY",
        expected_row_version=snapshot["row_version"],
        item_name=["直接解析牛奶"],
        item_kind=["product"],
        item_quantity=["1盒"],
        item_unit_price_yuan=["5.80"],
        item_amount_yuan=["5.80"],
        item_category=["生活"],
    )
    assert parsed.items[0].amount_cents == 580
    items = web_client.post(
        f"/web/expenses/{expense_id}/items/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(snapshot["row_version"]),
            "item_name": ["未保存牛奶", "未保存面包"],
            "item_kind": ["product", "product"],
            "item_quantity": ["1盒", "2个"],
            "item_unit_price_yuan": ["5.80", "3.25"],
            "item_amount_yuan": ["5.80", "1.234"],
            "item_category": ["生活", "餐饮"],
        },
        follow_redirects=False,
    )
    assert items.status_code == 422, items.text
    assert "未保存牛奶" in items.text
    assert "未保存面包" in items.text
    assert 'aria-describedby="item-1-amount-error"' in items.text

    splits = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(snapshot["row_version"]),
            "split_member_id": ["-1"],
            "split_amount_yuan": ["12.34"],
            "split_note": ["未保存分摊"],
        },
        follow_redirects=False,
    )
    assert splits.status_code == 422, splits.text
    assert "未保存分摊" in splits.text
    assert 'aria-describedby="split-0-member-error"' in splits.text


def test_received_split_web_edit_locks_agreed_facts_but_allows_metadata(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = _seed_pending_expense(source="bill_split_received")
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200, page.text
    assert "金额、商家和消费时间按协定冻结" in page.text
    assert 'name="amount_yuan"' in page.text
    assert 'name="merchant"' in page.text
    before = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()

    response = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(before["row_version"]),
            "original_currency": "CNY",
            "category": "家庭采购",
            "note": "协定后整理",
            "tags": "家庭",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    after = web_client.get(
        f"/api/expenses/{expense_id}", headers=identity.app_headers
    ).json()
    assert after["amount_cents"] == before["amount_cents"]
    assert after["merchant"] == before["merchant"]
    assert after["expense_time"] == before["expense_time"]
    assert after["category"] == "家庭采购"
    assert after["note"] == "协定后整理"
    assert after["tags"] == "家庭"


def test_web_detail_money_posts_fail_closed_after_env_drift(
    web_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    expense_id = _seed_pending_expense(currency_code="CNY")
    member_id = _owner_member_id()

    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    get_settings.cache_clear()
    try:
        item_snapshot = web_client.get(
            f"/api/expenses/{expense_id}", headers=identity.app_headers
        )
        assert item_snapshot.status_code == 200, item_snapshot.json()
        initial_row_version = item_snapshot.json()["row_version"]
        items = web_client.post(
            f"/web/expenses/{expense_id}/items/save",
            data={
                "ledger_id": "owner",
                "expected_row_version": initial_row_version,
                "item_name": ["牛奶"],
                "item_quantity": ["1盒"],
                "item_unit_price_yuan": ["12.34"],
                "item_amount_yuan": ["12.34"],
                "item_category": ["生活"],
            },
            follow_redirects=False,
        )
        assert items.status_code == 409, items.text
        assert "服务端币种配置与已持久化的本位币绑定不一致" in items.text
        api_items = web_client.get(
            f"/api/expenses/{expense_id}/items", headers=identity.app_headers
        )
        assert api_items.status_code == 200, api_items.json()
        assert api_items.json()["items"] == []

        split_snapshot = web_client.get(
            f"/api/expenses/{expense_id}", headers=identity.app_headers
        )
        assert split_snapshot.status_code == 200, split_snapshot.json()
        assert split_snapshot.json()["row_version"] == initial_row_version
        splits = web_client.post(
            f"/web/expenses/{expense_id}/splits/save",
            data={
                "ledger_id": "owner",
                "expected_row_version": split_snapshot.json()["row_version"],
                "split_member_id": [str(member_id)],
                "split_amount_yuan": ["12.34"],
                "split_note": ["整单"],
            },
            follow_redirects=False,
        )
        assert splits.status_code == 409, splits.text
        assert "服务端币种配置与已持久化的本位币绑定不一致" in splits.text
        api_splits = web_client.get(
            f"/api/expenses/{expense_id}/splits", headers=identity.app_headers
        )
        assert api_splits.status_code == 200, api_splits.json()
        assert api_splits.json()["splits"] == []
        final_snapshot = web_client.get(
            f"/api/expenses/{expense_id}", headers=identity.app_headers
        )
        assert final_snapshot.status_code == 200, final_snapshot.json()
        assert final_snapshot.json()["row_version"] == initial_row_version
    finally:
        get_settings.cache_clear()


def test_jpy_exact_split_does_not_render_a_false_zero_mismatch(
    web_client: TestClient,
) -> None:
    expense_id = _seed_pending_expense(amount_cents=1234, currency_code="JPY")
    _seed_detail_rows(expense_id)

    detail = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert detail.status_code == 200, detail.text
    assert "账单 ¥1234 · 已拆 ¥1234" in detail.text
    assert "· 差额" not in detail.text


def test_web_detail_rows_do_not_change_confirm_stats_or_export(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense(amount_cents=1234)
    _seed_detail_rows(expense_id)

    confirmed = web_confirm_expense(
        web_client, expense_id, identity=identity, follow_redirects=False
    )
    assert confirmed.status_code in {303, 307}, confirmed.text

    stats = web_client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 1234

    exported = web_client.get("/api/expenses/export.csv?month=2026-05", headers=identity.app_headers)
    assert exported.status_code == 200
    assert "家庭超市" in exported.text
    assert "12.34" in exported.text
    assert "牛奶" not in exported.text
    assert "我先记" not in exported.text


def test_web_detail_rows_are_read_only_for_viewer(web_client: TestClient) -> None:
    expense_id = _seed_pending_expense()
    _seed_detail_rows(expense_id)
    _demote_owner_ledger_to_viewer()

    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200
    assert "牛奶" in page.text
    assert "我先记" in page.text
    assert "保存明细" not in page.text
    assert "保存拆账" not in page.text
    assert "只读角色，无法修改小票明细" in page.text
    assert "disabled" in page.text

    item_write = web_client.post(
        f"/web/expenses/{expense_id}/items/save",
        data={"ledger_id": "owner", "item_name": ["不该写入"], "item_amount_yuan": ["0.01"]},
    )
    assert item_write.status_code == 403
    assert item_write.json()["error"] == "permission_denied"

    split_write = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "split_member_id": [str(_owner_member_id())],
            "split_amount_yuan": ["0.01"],
        },
    )
    assert split_write.status_code == 403
    assert split_write.json()["error"] == "permission_denied"
