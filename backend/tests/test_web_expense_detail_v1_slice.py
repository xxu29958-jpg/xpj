from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Expense, LedgerMember
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


def _seed_pending_expense(*, amount_cents: int = 1234) -> int:
    with SessionLocal() as db:
        now = now_utc()
        expense = Expense(
            tenant_id="owner",
            amount_cents=amount_cents,
            merchant="家庭超市",
            category="生活",
            note="周末采购",
            source="manual",
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
        ("GET", "/web/expenses/{expense_id}/edit"),
        ("POST", "/web/expenses/{expense_id}/save"),
        ("POST", "/web/expenses/{expense_id}/confirm"),
        ("POST", "/web/expenses/{expense_id}/items/save"),
        ("POST", "/web/expenses/{expense_id}/splits/save"),
        ("POST", "/web/expenses/{expense_id}/reject"),
    }
    seen: dict[tuple[str, str], list[str]] = {key: [] for key in expected}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        endpoint = getattr(route, "endpoint", None)
        for method, target_path in expected:
            if path == target_path and method in methods:
                seen[(method, target_path)].append(getattr(endpoint, "__module__", ""))

    for key, modules in seen.items():
        assert modules == ["app.routes.web_expense_edit"], f"{key} resolved to {modules}"


def _seed_detail_rows(expense_id: int) -> None:
    member_id = _owner_member_id()
    with SessionLocal() as db:
        replace_expense_items(
            db,
            expense_id,
            "owner",
            ExpenseItemReplaceRequest(
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
        replace_expense_splits(
            db,
            expense_id,
            "owner",
            ExpenseSplitReplaceRequest(
                splits=[ExpenseSplitRequest(member_id=member_id, amount_cents=1234, note="我先记")]
            ),
            actor_account_id=None,
        )


def test_web_edit_can_replace_receipt_items_and_family_splits(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense()
    member_id = _owner_member_id()

    items = web_client.post(
        f"/web/expenses/{expense_id}/items/save",
        data={
            "ledger_id": "owner",
            "item_name": ["牛奶", "面包", ""],
            "item_quantity": ["1盒", "2个", ""],
            "item_unit_price_yuan": ["", "3.25", ""],
            "item_amount_yuan": ["5.80", "6.50", ""],
            "item_category": ["生活", "餐饮", ""],
        },
        follow_redirects=False,
    )
    assert items.status_code in {303, 307}, items.text

    splits = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
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

    api_items = web_client.get(f"/api/expenses/{expense_id}/items", headers=identity.app_headers)
    assert api_items.status_code == 200, api_items.json()
    assert api_items.json()["items_total_amount_cents"] == 1230
    assert [item["name"] for item in api_items.json()["items"]] == ["牛奶", "面包"]

    api_splits = web_client.get(f"/api/expenses/{expense_id}/splits", headers=identity.app_headers)
    assert api_splits.status_code == 200, api_splits.json()
    assert api_splits.json()["splits_total_amount_cents"] == 1234


def test_web_detail_rows_do_not_change_confirm_stats_or_export(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense(amount_cents=1234)
    _seed_detail_rows(expense_id)

    confirmed = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={"ledger_id": "owner"},
        follow_redirects=False,
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
