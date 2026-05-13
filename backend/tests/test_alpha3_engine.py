"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from api_contract_helpers import insert_confirmed_expense, upload_png
from app.database import SessionLocal
from app.models import Expense, LedgerMember, RuleApplicationBatch, RuleApplicationChange
from conftest import app_headers, gray_app_headers


# --- T17 Rules Preview ----------------------------------------------------


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str) -> None:
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=app_headers(),
        json={"merchant": merchant, "amount_cents": 3800},
    )
    assert response.status_code == 200


def test_rule_preview_does_not_modify(client: TestClient) -> None:
    first_id = upload_png(client)
    _set_pending_merchant(client, first_id, "STARBUCKS COFFEE")

    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
        json={
            "keyword": "STARBUCKS",
            "target_category": "餐饮",
            "match_field": "merchant",
            "limit": 10,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] >= 1
    assert len(body["items"]) >= 1
    first = body["items"][0]
    assert first["merchant"] == "STARBUCKS COFFEE"
    assert first["suggested_category"] == "餐饮"
    assert "STARBUCKS" in first["reason"]

    # Database not mutated.
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == first_id))
        assert expense is not None
        # Original category remains "其他" because we never applied.
        assert expense.category == "其他"


def test_rule_preview_rejects_empty_keyword(client: TestClient) -> None:
    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
        json={"keyword": "   ", "target_category": "餐饮"},
    )
    assert response.status_code == 422


def test_rule_preview_caps_items_by_limit(client: TestClient) -> None:
    ids: list[int] = []
    for index in range(3):
        new_id = upload_png(client)
        _set_pending_merchant(client, new_id, f"星巴克门店-{index}")
        ids.append(new_id)

    response = client.post(
        "/api/rules/preview",
        headers=app_headers(),
        json={"keyword": "星巴克", "target_category": "餐饮", "limit": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched_count"] == 3
    assert len(body["items"]) == 2


# --- T18 Rules Apply Pending ---------------------------------------------


def test_rule_apply_pending_preview_does_not_modify_and_reports_scope(
    client: TestClient,
) -> None:
    default_id = upload_png(client)
    _set_pending_merchant(client, default_id, "Starbucks 上海")
    custom_id = upload_png(client)
    custom = client.patch(
        f"/api/expenses/{custom_id}",
        headers=app_headers(),
        json={"merchant": "Starbucks 手动分类", "category": "交通", "amount_cents": 1000},
    )
    assert custom.status_code == 200

    response = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert response.status_code == 200

    preview = client.post(
        "/api/rules/apply-pending/preview?limit=10",
        headers=app_headers(),
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["pending_scanned"] >= 2
    assert body["changed_count"] == 1
    assert body["skipped_non_default_category"] == 1
    assert body["conflict_count"] == 0
    assert body["items"] == [
        {
            "id": default_id,
            "merchant": "Starbucks 上海",
            "current_category": "其他",
            "suggested_category": "餐饮",
            "rule_keyword": "Starbucks",
            "reason": "规则[Starbucks] 将分类改为 餐饮",
        }
    ]

    with SessionLocal() as db:
        default = db.scalar(select(Expense).where(Expense.id == default_id))
        custom_expense = db.scalar(select(Expense).where(Expense.id == custom_id))
        assert default is not None
        assert custom_expense is not None
        assert default.category == "其他"
        assert custom_expense.category == "交通"


def test_rule_apply_pending_updates_category(client: TestClient) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "Starbucks 上海")

    # Seed a rule for Starbucks → 餐饮 with high priority.
    response = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert response.status_code == 200

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["pending_scanned"] >= 1
    assert body["changed_count"] >= 1

    pending = client.get("/api/expenses/pending", headers=app_headers())
    assert pending.status_code == 200
    items = pending.json()
    target = next((item for item in items if int(item["id"]) == pending_id), None)
    assert target is not None
    assert target["category"] == "餐饮"
    assert target["status"] == "pending"  # NOT auto-confirmed


def test_rule_apply_pending_creates_application_batch_and_changes(
    client: TestClient,
) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "AuditCafe 上海")
    created = client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "AuditCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    response = client.post("/api/rules/apply-pending", headers=app_headers())

    assert response.status_code == 200
    assert response.json()["changed_count"] == 1
    with SessionLocal() as db:
        batch = db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.tenant_id == "owner"))
        assert batch is not None
        assert batch.public_id
        assert batch.status == "applied"
        assert batch.changed_count == 1
        assert batch.actor_account_id is not None
        assert batch.actor_device_id is not None
        change = db.scalar(
            select(RuleApplicationChange)
            .where(RuleApplicationChange.tenant_id == "owner")
            .where(RuleApplicationChange.batch_id == batch.id)
        )
        assert change is not None
        assert change.expense_id == pending_id
        assert change.rule_id == rule_id
        assert change.matched_keyword == "AuditCafe"
        assert change.before_category == "其他"
        assert change.after_category == "餐饮"
        assert change.status == "applied"

    listed = client.get("/api/rules/applications", headers=app_headers())
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["public_id"] == batch.public_id
    assert item["status"] == "applied"
    assert item["changed_count"] == 1


def test_rule_apply_pending_without_changes_creates_no_application_batch(
    client: TestClient,
) -> None:
    upload_png(client)

    response = client.post("/api/rules/apply-pending", headers=app_headers())

    assert response.status_code == 200
    assert response.json()["changed_count"] == 0
    applications = client.get("/api/rules/applications", headers=app_headers())
    assert applications.status_code == 200
    assert applications.json()["items"] == []


def test_rule_application_rollback_reverts_only_matching_after_category(
    client: TestClient,
) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "RollbackCafe")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "RollbackCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    applied = client.post("/api/rules/apply-pending", headers=app_headers())
    assert applied.status_code == 200
    batch_id = client.get("/api/rules/applications", headers=app_headers()).json()["items"][0]["public_id"]

    rollback = client.post(
        f"/api/rules/applications/{batch_id}/rollback",
        headers=app_headers(),
    )

    assert rollback.status_code == 200
    assert rollback.json()["changed"] == 1
    assert rollback.json()["skipped"] == 0
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "其他"
        change = db.scalar(select(RuleApplicationChange).where(RuleApplicationChange.expense_id == pending_id))
        assert change is not None
        assert change.status == "rolled_back"
        assert change.rolled_back_at is not None


def test_rule_application_second_rollback_skips_already_handled_changes(
    client: TestClient,
) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "SecondRollbackCafe")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "SecondRollbackCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    client.post("/api/rules/apply-pending", headers=app_headers())
    batch_id = client.get("/api/rules/applications", headers=app_headers()).json()["items"][0]["public_id"]
    first = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=app_headers())
    assert first.status_code == 200
    assert first.json()["changed"] == 1

    second = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=app_headers())

    assert second.status_code == 200
    assert second.json()["changed"] == 0
    assert second.json()["skipped"] == 1


def test_rule_application_rollback_skips_manual_category_edits(
    client: TestClient,
) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "ManualEditCafe")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "ManualEditCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    client.post("/api/rules/apply-pending", headers=app_headers())
    batch_id = client.get("/api/rules/applications", headers=app_headers()).json()["items"][0]["public_id"]
    manual = client.patch(
        f"/api/expenses/{pending_id}",
        headers=app_headers(),
        json={"category": "交通"},
    )
    assert manual.status_code == 200

    rollback = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=app_headers())

    assert rollback.status_code == 200
    assert rollback.json()["changed"] == 0
    assert rollback.json()["skipped"] == 1
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"
        change = db.scalar(select(RuleApplicationChange).where(RuleApplicationChange.expense_id == pending_id))
        assert change is not None
        assert change.status == "skipped"


def test_rule_applications_are_not_visible_or_rollbackable_cross_ledger(
    client: TestClient,
) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "PrivateRuleCafe")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "PrivateRuleCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    client.post("/api/rules/apply-pending", headers=app_headers())
    batch_id = client.get("/api/rules/applications", headers=app_headers()).json()["items"][0]["public_id"]

    gray_list = client.get("/api/rules/applications", headers=gray_app_headers())
    gray_rollback = client.post(
        f"/api/rules/applications/{batch_id}/rollback",
        headers=gray_app_headers(),
    )

    assert gray_list.status_code == 200
    assert all(item["public_id"] != batch_id for item in gray_list.json()["items"])
    assert gray_rollback.status_code == 404
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "餐饮"


def test_viewer_cannot_rollback_rule_application(client: TestClient) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "ViewerRollbackCafe")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "ViewerRollbackCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    client.post("/api/rules/apply-pending", headers=app_headers())
    batch_id = client.get("/api/rules/applications", headers=app_headers()).json()["items"][0]["public_id"]
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()

    response = client.post(
        f"/api/rules/applications/{batch_id}/rollback",
        headers=app_headers(),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"


def test_rule_apply_pending_does_not_touch_confirmed(client: TestClient) -> None:
    confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="Starbucks 北京",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        assert expense is not None
        # Confirmed records are never re-classified by apply-pending.
        assert expense.category == "其他"
        assert expense.status == "confirmed"


def test_rule_apply_pending_does_not_auto_confirm(client: TestClient) -> None:
    pending_id = upload_png(client)
    _set_pending_merchant(client, pending_id, "Kimi 订阅")
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Kimi", "category": "AI订阅", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.status == "pending"


def test_rule_apply_pending_skips_non_default_category(client: TestClient) -> None:
    pending_id = upload_png(client)
    # Already classified as 交通 — apply-pending must respect user choice.
    response = client.patch(
        f"/api/expenses/{pending_id}",
        headers=app_headers(),
        json={"merchant": "Starbucks", "category": "交通", "amount_cents": 1000},
    )
    assert response.status_code == 200
    client.post(
        "/api/rules/categories",
        headers=app_headers(),
        json={"keyword": "Starbucks", "category": "餐饮", "enabled": True, "priority": 1},
    )

    response = client.post("/api/rules/apply-pending", headers=app_headers())
    assert response.status_code == 200

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"


# --- T24 Recurring candidates --------------------------------------------


def test_recurring_candidates_empty(client: TestClient) -> None:
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_recurring_candidates_detects_monthly_merchant(client: TestClient) -> None:
    # 3 months of ChatGPT subscription, amounts within 15%.
    base = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for month_offset, amount in [(2, 20000), (1, 20000), (0, 20800)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="ChatGPT Plus",
            category="AI订阅",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    chatgpt = next((item for item in items if "ChatGPT" in item["merchant"]), None)
    assert chatgpt is not None
    assert chatgpt["occurrence_count"] >= 2
    assert chatgpt["confidence"] in {"medium", "high"}
    assert chatgpt["amount_cents"] > 0


def test_recurring_candidates_ignores_one_off(client: TestClient) -> None:
    when = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    insert_confirmed_expense(
        amount_cents=99900,
        merchant="一次性家电",
        category="其他",
        expense_time=when,
        confirmed_at=when,
    )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("一次性家电" not in item["merchant"] for item in items)


def test_recurring_candidates_ignores_amount_drift(client: TestClient) -> None:
    # Same merchant 3 months but amounts way off → excluded.
    base = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    for month_offset, amount in [(2, 5000), (1, 30000), (0, 18000)]:
        when = base - timedelta(days=30 * month_offset)
        insert_confirmed_expense(
            amount_cents=amount,
            merchant="水电费",
            category="住房",
            expense_time=when,
            confirmed_at=when,
        )
    response = client.get("/api/insights/recurring-candidates", headers=app_headers())
    assert response.status_code == 200
    items = response.json()["items"]
    assert all("水电费" not in item["merchant"] for item in items)


# --- No-secret-leak smoke -------------------------------------------------


def test_alpha3_endpoints_no_secret_leak(client: TestClient) -> None:
    upload_png(client)
    for path, method, body in [
        ("/api/rules/preview", "POST", {"keyword": "x", "target_category": "餐饮"}),
        ("/api/rules/apply-pending/preview", "POST", None),
        ("/api/rules/apply-pending", "POST", None),
        ("/api/insights/recurring-candidates", "GET", None),
    ]:
        if method == "GET":
            response = client.get(path, headers=app_headers())
        else:
            response = client.post(path, headers=app_headers(), json=body)
        assert response.status_code == 200
        text = response.text
        assert "token_hash" not in text
        assert "upload_key" not in text
        assert "E:\\" not in text
