"""Tests for /web/categories + /web/categories/uncategorized (M3 / T10-T13).

Covers:
* normalize_merchant whitespace + case folding (no schema change).
* /web/categories renders the category dashboard with month aggregation.
* /web/categories/uncategorized lists only uncategorized pending rows.
* Bulk-set-category updates only the selected rows + flips them out of
  the uncategorized bucket.
* No secrets (token / upload_key / absolute paths) leak in the HTML.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.main import app
from app.models import ApiIdempotencyKey, Budget, BudgetCategory, CategoryRule, Expense, Goal, Ledger
from app.routes.web_app import _require_local as _web_require_local
from app.schemas import ExpenseUpdateRequest
from app.services import pending_review_bulk_service
from app.services.category_preference_service import ensure_category_preference_for_name
from app.services.category_service import (
    list_category_summary,
    normalize_existing_expense_categories,
)
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.expense_accounting_time_service import refresh_legacy_expense_time
from app.services.merchant_service import display_merchant, normalize_merchant
from app.services.time_service import now_utc
from tests._infra.env import BACKEND_ROOT

# ── Fixtures (mirror tests/test_web_app.py setup) ───────────────────────────


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def _create_pending(client: TestClient, *, identity) -> int:
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


def _save_pending(
    web_client: TestClient,
    expense_id: int,
    *,
    identity,
    amount_yuan: str,
    merchant: str,
    category: str,
) -> None:
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": category,
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert resp.status_code in {303, 307}, resp.text


def _create_manual_category(
    client: TestClient,
    *,
    identity,
    category: str,
    client_ref: str,
) -> None:
    resp = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "home_currency_code": "CNY", "amount_cents": 1200,
            "merchant": "分类测试",
            "category": category,
            "client_ref": client_ref,
        },
    )
    assert resp.status_code == 200, resp.text


def _category_preference(client: TestClient, *, identity, name: str) -> dict:
    resp = client.get(
        "/api/expenses/categories/preferences",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200, resp.text
    return next(item for item in resp.json()["items"] if item["name"] == name)


# ── T10: merchant_service.normalize_merchant ───────────────────────────────


def test_normalize_merchant_basic() -> None:
    assert normalize_merchant("  Starbucks  ") == "starbucks"
    assert normalize_merchant("星巴克\u3000国贸店") == "星巴克 国贸店"
    assert normalize_merchant("STARBUCKS\t\t国贸店") == "starbucks 国贸店"
    assert normalize_merchant(None) == ""
    assert normalize_merchant("   ") == ""
    # Zero-width characters get scrubbed.
    assert normalize_merchant("Star\u200bbucks") == "star bucks"
    assert normalize_merchant("星巴克（自动）") == "星巴克"


def test_display_merchant_preserves_case() -> None:
    assert display_merchant("  Starbucks 国贸  ") == "Starbucks 国贸"
    assert display_merchant(None) == ""


# ── T12: /web/categories dashboard ─────────────────────────────────────────


def test_web_categories_renders_with_navigation(web_client: TestClient) -> None:
    resp = web_client.get("/web/categories?ledger_id=owner")
    assert resp.status_code == 200
    # Canonical section lives under the real Reference Library hub.
    assert '<h1 class="page-title">分类</h1>' in resp.text
    assert 'data-page-level="tertiary"' in resp.text
    assert any(href == "/web/library?ledger_id=owner" and "资料库" in label
        for href, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S))
    assert 'href="/web/rules?ledger_id=owner"' in resp.text
    assert 'aria-label="选择分类月份"' in resp.text


def test_web_categories_counts_pending_uncategorized(web_client: TestClient, *, identity) -> None:
    # A missing category is distinct from the user's valid choice of 其他.
    missing = _create_pending(web_client, identity=identity)
    _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        db.get(Expense, missing).category = ""
        db.commit()
    resp = web_client.get("/web/categories?ledger_id=owner")
    assert resp.status_code == 200
    assert "1 条待确认还未分类" in resp.text
    # A direct entry to the cleanup workflow is rendered.
    assert "/web/categories/uncategorized?ledger_id=owner" in resp.text


def test_category_summary_uses_stat_time_and_normalized_category_aliases(
    web_client: TestClient,
) -> None:
    with SessionLocal() as db:
        now = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
        _calendar_expenses = [
                Expense(
                    tenant_id="owner",
                    amount_cents=1200,
                    merchant="补录五月",
                    category="餐饮",
                    status="confirmed",
                    expense_time=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                Expense(
                    tenant_id="owner",
                    amount_cents=800,
                    merchant="旧分类五月",
                    category="吃饭",
                    status="confirmed",
                    expense_time=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
                    confirmed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        for expense in _calendar_expenses:
            if expense.status == "confirmed":
                refresh_legacy_expense_time(db, expense)
        db.add_all(_calendar_expenses)
        db.commit()
        dashboard = list_category_summary(db, tenant_id="owner", month="2026-05")

    food = next(item for item in dashboard.summaries if item.category == "餐饮")
    assert food.confirmed_count == 2
    assert food.confirmed_amount_cents == 2000

    # Once all Expense rows are canonical, a legacy CategoryRule still needs
    # independent normalization; it must not be hidden by an Expense-only
    # early return.
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        legacy_expense = db.scalar(select(Expense).where(Expense.merchant == "旧分类五月"))
        assert legacy_expense is not None
        legacy_expense.category = "餐饮"
        db.add(
            CategoryRule(
                tenant_id="owner",
                keyword="legacy-food-rule",
                category="吃饭",
                enabled=True,
                priority=10,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    with SessionLocal() as db:
        normalize_existing_expense_categories(db, "owner")
        rule = db.scalar(select(CategoryRule).where(CategoryRule.keyword == "legacy-food-rule"))
        assert rule is not None
        assert rule.category == "餐饮"


# ── T13: /web/categories/uncategorized ─────────────────────────────────────


def test_category_summary_preserves_adopted_month_across_query_timezones(
    web_client: TestClient,
) -> None:
    del web_client
    with SessionLocal() as db:
        now = datetime(2026, 5, 1, 1, 0, tzinfo=UTC)
        _calendar_expense = Expense(
            tenant_id="owner",
            amount_cents=990,
            merchant="Boundary Cafe",
            category="Boundary",
            status="confirmed",
            expense_time=datetime(2026, 4, 30, 16, 30, tzinfo=UTC),
            confirmed_at=now,
            created_at=now,
            updated_at=now,
        )
        refresh_legacy_expense_time(db, _calendar_expense)
        db.add(_calendar_expense)
        db.commit()
        shanghai = list_category_summary(
            db,
            tenant_id="owner",
            month="2026-05",
            timezone_name="Asia/Shanghai",
        )
        utc = list_category_summary(
            db,
            tenant_id="owner",
            month="2026-05",
            timezone_name="UTC",
        )

    assert any(item.category == "Boundary" for item in shanghai.summaries)
    assert any(item.category == "Boundary" for item in utc.summaries)


def test_custom_category_preference_delete_restore_controls_options(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-coffee"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    assert preference["usage_count"] == 1
    categories = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" in categories.json()["items"]

    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    hidden = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" not in hidden.json()["items"]

    recycle = client.get("/api/recycle-bin", headers=identity.app_headers)
    assert recycle.status_code == 200
    assert any(
        item["kind"] == "category_preference" and item["title"] == "咖啡"
        for item in recycle.json()["items"]
    )

    restored = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/restore",
        headers=identity.app_headers,
        json={"expected_row_version": deleted.json()["row_version"]},
    )
    assert restored.status_code == 200, restored.text
    visible = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert "咖啡" in visible.json()["items"]


def test_deleted_preference_suppresses_historical_fallback_only_for_that_key(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-hide"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 200, deleted.text
    with SessionLocal() as db:
        now = now_utc()
        _calendar_expense = Expense(
            tenant_id="owner",
            amount_cents=900,
            merchant="历史手作",
            category="手作",
            status="confirmed",
            expense_time=now,
            confirmed_at=now,
            created_at=now,
            updated_at=now,
        )
        refresh_legacy_expense_time(db, _calendar_expense)
        db.add(_calendar_expense)
        db.commit()

    categories = client.get("/api/expenses/categories", headers=identity.app_headers)
    assert categories.status_code == 200
    assert "咖啡" not in categories.json()["items"]
    assert "手作" in categories.json()["items"]


def test_default_category_usage_does_not_create_custom_preference(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="吃饭", client_ref="cat-pref-default"
    )
    resp = client.get(
        "/api/expenses/categories/preferences",
        headers=identity.app_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_delete_category_preference_rejects_active_rule_reference(
    client: TestClient, *, identity
) -> None:
    _create_manual_category(
        client, identity=identity, category="咖啡", client_ref="cat-pref-rule"
    )
    preference = _category_preference(client, identity=identity, name="咖啡")
    preview_path = f"/api/expenses/categories/preferences/{preference['public_id']}"
    assert client.get(preview_path).status_code == 401
    before_reference = client.get(preview_path, headers=identity.app_headers)
    assert before_reference.status_code == 200, before_reference.text
    assert before_reference.json() == {"category": preference, "references": []}
    with SessionLocal() as db:
        now = now_utc()
        ensure_category_preference_for_name(db, tenant_id="owner", name="咖啡")
        rule = CategoryRule(
            tenant_id="owner", keyword="coffee", category="咖啡",
            enabled=True, priority=10, created_at=now, updated_at=now,
        )
        db.add(rule)
        owner_id = db.scalar(select(Ledger.owner_account_id).where(Ledger.ledger_id == "owner"))
        db.add(Ledger(ledger_id="category-reference-other", name="另一本账本", owner_account_id=owner_id))
        db.flush()
        db.add_all([
            CategoryRule(tenant_id="owner", keyword="disabled-coffee", category="咖啡",
                enabled=False, priority=10, created_at=now, updated_at=now),
            CategoryRule(tenant_id="owner", keyword="deleted-coffee", category="咖啡",
                enabled=True, priority=10, created_at=now, updated_at=now, deleted_at=now),
            CategoryRule(tenant_id="category-reference-other", keyword="其他账本的私人规则", category="咖啡",
                enabled=True, priority=10, created_at=now, updated_at=now),
            Budget(tenant_id="owner", month="2026-09", home_currency_code="CNY",
                total_amount_cents=50000, excluded_categories='["咖啡"]', archived_at=now),
            Budget(tenant_id="category-reference-other", month="2026-10", home_currency_code="CNY",
                total_amount_cents=50000, excluded_categories='["咖啡"]'),
            Goal(tenant_id="owner", name="已归档的咖啡目标", month="2026-09", category="咖啡",
                target_amount_cents=5000, home_currency_code="CNY", status="archived", archived_at=now),
            Goal(tenant_id="category-reference-other", name="其他账本的私人目标", month="2026-10", category="咖啡",
                target_amount_cents=5000, home_currency_code="CNY", status="active"),
        ])
        db.flush()
        db.add_all([
            BudgetCategory(tenant_id="owner", month="2026-09", category="咖啡", amount_cents=5000),
            BudgetCategory(tenant_id="category-reference-other", month="2026-10", category="咖啡", amount_cents=5000),
        ])
        db.commit()
        rule_id = rule.id

    preview = client.get(preview_path, headers=identity.app_headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["category"] == preference
    assert preview.json()["references"] == [
        {"kind": "rule", "id": str(rule_id), "label": "规则「coffee」"},
    ]
    assert client.get(preview_path, headers=identity.gray_app_headers).status_code == 404

    deleted = client.post(
        f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers,
        json={"expected_row_version": preference["row_version"]},
    )
    assert deleted.status_code == 409
    assert deleted.json()["error"] == "state_conflict"
    assert deleted.json().get("category_references") == [
        {"kind": "rule", "id": str(rule_id), "label": "规则「coffee」"},
    ], "only active references in this ledger may be exposed as a blocker"
    assert _category_preference(client, identity=identity, name="咖啡") == preference


@pytest.mark.parametrize("source", ["budget_category", "budget_exclusion", "budget_category_and_exclusion", "spending_goal"])
def test_category_rejection_identifies_the_saved_plan_without_changing_it(client: TestClient, identity, source: str) -> None:
    _create_manual_category(client, identity=identity, category="咖啡", client_ref=f"category-plan-{source}")
    preference = _category_preference(client, identity=identity, name="咖啡")
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    if source == "spending_goal":
        created = client.post("/api/goals", headers=headers, json={"home_currency_code": "CNY",
            "name": "十月咖啡安排", "month": "2026-10", "category": "咖啡", "target_amount_cents": 5000})
        assert created.status_code == 201, created.text
        kind, identifier = "goal", created.json()["public_id"]
        read_url = f"/api/goals/{identifier}"
    else:
        created = client.put("/api/budgets/monthly/2026-10", headers=headers,
            json={"home_currency_code": "CNY", "expected_row_version": None, "total_amount_cents": 50000,
                "excluded_categories": ["咖啡"] if source in {"budget_exclusion", "budget_category_and_exclusion"} else [],
                "category_budgets": [{"category": "咖啡", "amount_cents": 5000}]
                    if source in {"budget_category", "budget_category_and_exclusion"} else []})
        assert created.status_code == 200, created.text
        kind, identifier = "budget", "2026-10"
        read_url = "/api/budgets/monthly?month=2026-10"

    original = client.get(read_url, headers=identity.app_headers).json()
    preview = client.get(f"/api/expenses/categories/preferences/{preference['public_id']}", headers=identity.app_headers)
    assert preview.status_code == 200, preview.text
    assert [(item["kind"], item["id"]) for item in preview.json()["references"]] == [(kind, identifier)]
    assert _category_preference(client, identity=identity, name="咖啡") == preference
    rejected = client.post(f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers, json={"expected_row_version": preference["row_version"]})
    assert rejected.status_code == 409, rejected.text
    references = rejected.json().get("category_references", [])
    assert [(item["kind"], item["id"]) for item in references] == [(kind, identifier)]
    assert "十月咖啡安排" in references[0]["label"] if kind == "goal" else "2026-10" in references[0]["label"]
    assert preview.json()["references"] == references
    assert client.get(read_url, headers=identity.app_headers).json() == original
    assert _category_preference(client, identity=identity, name="咖啡") == preference


def test_category_rejection_lists_every_blocker_once(client: TestClient, identity) -> None:
    _create_manual_category(client, identity=identity, category="咖啡", client_ref="category-all-references")
    preference = _category_preference(client, identity=identity, name="咖啡")
    with SessionLocal() as db:
        rule = CategoryRule(tenant_id="owner", keyword="coffee", category="咖啡", enabled=True, priority=10)
        budget = Budget(tenant_id="owner", month="2026-10", home_currency_code="CNY",
            total_amount_cents=50000, excluded_categories='["咖啡"]')
        goal = Goal(tenant_id="owner", name="十月咖啡安排", month="2026-10", category="咖啡",
            target_amount_cents=5000, home_currency_code="CNY", status="active")
        db.add_all([rule, budget, goal])
        db.flush()
        db.add(BudgetCategory(tenant_id="owner", month="2026-10", category="咖啡", amount_cents=5000))
        db.commit()
        rule_id, goal_id = str(rule.id), goal.public_id
    rejected = client.post(f"/api/expenses/categories/preferences/{preference['public_id']}/delete",
        headers=identity.app_headers, json={"expected_row_version": preference["row_version"]})
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["category_references"] == [
        {"kind": "rule", "id": rule_id, "label": "规则「coffee」"},
        {"kind": "budget", "id": "2026-10", "label": "预算「2026-10」"},
        {"kind": "goal", "id": goal_id, "label": "目标「十月咖啡安排」"},
    ]
    assert _category_preference(client, identity=identity, name="咖啡") == preference


def test_web_uncategorized_lists_only_uncategorized(web_client: TestClient, *, identity) -> None:
    eid_other = _create_pending(web_client, identity=identity)  # stays "其他"
    eid_food = _create_pending(web_client, identity=identity)
    _save_pending(
        web_client, eid_food, identity=identity,
        amount_yuan="12.34", merchant="星巴克", category="餐饮",
    )
    dashboard = web_client.get("/web/categories?ledger_id=owner")
    assert "1 条待确认使用「其他」分类" in dashboard.text
    assert "filter=including_other" in dashboard.text
    eid_missing = _create_pending(web_client, identity=identity)
    with SessionLocal() as db:
        db.get(Expense, eid_missing).category = "未分類"
        db.commit()
    resp = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert resp.status_code == 200
    ids = set(re.findall(r'name="expense_snapshot" value="(\d+):', resp.text))
    assert str(eid_missing) in ids
    assert str(eid_other) not in ids
    assert str(eid_food) not in ids
    including_other = web_client.get("/web/categories/uncategorized?ledger_id=owner&filter=including_other")
    assert f'name="expense_snapshot" value="{eid_other}:' in including_other.text


def test_web_uncategorized_bulk_set_category(web_client: TestClient, *, identity) -> None:
    eid = _create_pending(web_client, identity=identity)
    original = web_client.get("/web/categories/uncategorized?ledger_id=owner&filter=including_other")
    snapshot = re.search(rf'name="expense_snapshot" value="({eid}:\d+)"', original.text)[1]
    resp = web_client.post(
        "/web/categories/uncategorized/bulk-set",
        data={
            "ledger_id": "owner",
            "expense_snapshot": [snapshot],
            "idempotency_key": re.search(r'name="idempotency_key" value="([^"]+)"', original.text)[1],
            "category": "餐饮",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200, resp.text
    assert 'aria-label="继续逐笔核对"' in resp.text
    with SessionLocal() as db:
        row = db.get(Expense, eid)
        assert row.status == "pending" and row.category == "餐饮"
    follow = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert follow.status_code == 200
    ids = set(re.findall(r'name="expense_snapshot" value="(\d+):', follow.text))
    # Row flipped out of the uncategorized bucket.
    assert str(eid) not in ids


def test_web_uncategorized_bulk_requires_selection(web_client: TestClient) -> None:
    resp = web_client.post(
        "/web/categories/uncategorized/bulk-set",
        data={"ledger_id": "owner", "category": "餐饮"},
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "请勾选要修改的账单。" in resp.text


def test_category_batch_rolls_back_real_writes_and_replays_its_first_result(web_client, identity, monkeypatch):
    identities = [_create_pending(web_client, identity=identity) for _ in range(2)]
    with SessionLocal() as db:
        before = {identity: (db.get(Expense, identity).category, db.get(Expense, identity).row_version) for identity in identities}
    command = str(uuid4())
    fields = {"ledger_id": "owner", "category": "购物", "idempotency_key": command,
        "expense_snapshot": [f"{identity}:{before[identity][1]}" for identity in identities]}
    update = pending_review_bulk_service.update_expense

    def interrupted(db, expense_id, *args, **kwargs):
        if expense_id == identities[1]:
            raise SQLAlchemyError("controlled second-row storage interruption")
        return update(db, expense_id, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(pending_review_bulk_service, "update_expense", interrupted)
        rejected = web_client.post("/web/categories/uncategorized/bulk-set", data=fields)
        assert rejected.status_code == 503, rejected.text
    with SessionLocal() as db:
        assert {identity: (db.get(Expense, identity).category, db.get(Expense, identity).row_version)
            for identity in identities} == before
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == command)) is None
    accepted = web_client.post("/web/categories/uncategorized/bulk-set", data=fields)
    assert accepted.status_code == 200 and "已更新 2 条" in accepted.text, accepted.text
    with SessionLocal() as db:
        first = db.get(Expense, identities[0])
        update(db, first.id, "owner", ExpenseUpdateRequest(category="医疗", expected_row_version=first.row_version))
        peer_version = first.row_version
    replay = web_client.post("/web/categories/uncategorized/bulk-set", data=fields)
    assert replay.status_code == 200 and "已更新 2 条" in replay.text, replay.text
    changed_intent = web_client.post("/web/categories/uncategorized/bulk-set", data={**fields, "category": "交通"})
    assert changed_intent.status_code == 422, changed_intent.text
    with SessionLocal() as db:
        assert (db.get(Expense, identities[0]).category, db.get(Expense, identities[0]).row_version) == ("医疗", peer_version)
        assert db.get(Expense, identities[1]).category == "购物"
        assert all(db.get(Expense, identity).status == "pending" for identity in identities)
        receipt = db.scalars(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == command)).one()
        assert receipt.response_body["result"]["success_ids"] == identities


# ── Loopback gate + secret-leak guard ─────────────────────────────────────


def test_web_categories_remote_returns_403(client: TestClient) -> None:
    assert client.get("/web/categories").status_code == 403
    assert client.get("/web/categories/uncategorized").status_code == 403


def test_web_categories_no_secret_leak(web_client: TestClient, *, identity) -> None:
    _create_pending(web_client, identity=identity)
    for path in ("/web/categories?ledger_id=owner", "/web/categories/uncategorized?ledger_id=owner"):
        resp = web_client.get(path)
        assert resp.status_code == 200
        body = resp.text
        assert identity.app_token not in body
        assert identity.admin_token not in body
        assert identity.upload_key not in body
        assert str(BACKEND_ROOT) not in body


def test_web_uncategorized_includes_dirty_tokens(web_client: TestClient, *, identity) -> None:
    """Legacy missing tokens use the same caliber as the inbox and data quality."""
    with SessionLocal() as db:
        token_none = Expense(
            tenant_id="owner", amount_cents=100, merchant="商家甲", category="none",
            source="pytest", status="pending", duplicate_status="none",
        )
        token_trad = Expense(
            tenant_id="owner", amount_cents=200, merchant="商家乙", category="未分類",
            source="pytest", status="pending", duplicate_status="none",
        )
        categorized = Expense(
            tenant_id="owner", amount_cents=300, merchant="商家丙", category="餐饮",
            source="pytest", status="pending", duplicate_status="none",
        )
        db.add_all([token_none, token_trad, categorized])
        db.commit()
        none_id, trad_id, cat_id = token_none.id, token_trad.id, categorized.id

    resp = web_client.get("/web/categories/uncategorized?ledger_id=owner")
    assert resp.status_code == 200
    ids = set(re.findall(r'name="expense_snapshot" value="(\d+):', resp.text))
    assert str(none_id) in ids
    assert str(trad_id) in ids
    assert str(cat_id) not in ids
