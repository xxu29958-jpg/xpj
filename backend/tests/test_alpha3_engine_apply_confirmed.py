"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from datetime import UTC, datetime

from api_contract_helpers import insert_confirmed_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerMember, RuleApplicationBatch, RuleApplicationChange


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str, *, identity) -> None:
    response = client.patch(
        f"/api/expenses/{expense_id}",
        headers=identity.app_headers,
        json={"merchant": merchant, "amount_cents": 3800},
    )
    assert response.status_code == 200


def _apply_pending_rules(client: TestClient, *, identity, max_scan: int = 500):
    preview = client.post(
        f"/api/rules/apply-pending/preview?max_scan={max_scan}",
        headers=identity.app_headers,
    )
    assert preview.status_code == 200, preview.json()
    token = preview.json()["preview_token"]
    return client.post(
        f"/api/rules/apply-pending?max_scan={max_scan}",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": token},
    )


def test_rule_apply_confirmed_dry_run_then_confirm_integration(
    client: TestClient, *, identity,
) -> None:
    confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="ConfirmedApplyCafe",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    non_matching_id = insert_confirmed_expense(
        amount_cents=6200,
        merchant="ConfirmedApplyCafe",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 5, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 5, tzinfo=UTC),
    )
    with SessionLocal() as db:
        target = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        other = db.scalar(select(Expense).where(Expense.id == non_matching_id))
        assert target is not None and other is not None
        target.tags = "真香"
        other.tags = "必要"
        db.commit()
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "ConfirmedApplyCafe",
            "category": "餐饮",
            "enabled": True,
            "priority": 1,
            "amount_min_cents": 1000,
            "amount_max_cents": 5000,
            "source_contains": "pytest",
            "tag_contains": "真香",
        },
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]
    assert created.json()["amount_min_cents"] == 1000
    assert created.json()["tag_contains"] == "真香"

    preview = client.post("/api/rules/apply-confirmed", headers=identity.app_headers)

    assert preview.status_code == 200
    body = preview.json()
    assert body["dry_run"] is True
    assert body["confirmed_scanned"] >= 1
    assert body["changed_count"] == 1
    assert body["items"][0]["id"] == confirmed_id
    assert body["preview_token"]
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        other = db.scalar(select(Expense).where(Expense.id == non_matching_id))
        assert expense is not None
        assert expense.category == "其他"
        assert other is not None
        assert other.category == "其他"
        assert db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.tenant_id == "owner")) is None

    response = client.post(
        "/api/rules/apply-confirmed",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": body["preview_token"]},
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is False
    assert response.json()["changed_count"] == 1
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        other = db.scalar(select(Expense).where(Expense.id == non_matching_id))
        assert expense is not None
        assert expense.category == "餐饮"
        assert expense.status == "confirmed"
        assert other is not None
        assert other.category == "其他"
        batch = db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.tenant_id == "owner"))
        assert batch is not None
        assert batch.status == "applied_confirmed"
        assert batch.changed_count == 1
        assert batch.actor_account_id is not None
        assert batch.actor_device_id is not None
        change = db.scalar(
            select(RuleApplicationChange)
            .where(RuleApplicationChange.tenant_id == "owner")
            .where(RuleApplicationChange.batch_id == batch.id)
        )
        assert change is not None
        assert change.expense_id == confirmed_id
        assert change.rule_id == rule_id
        assert change.before_category == "其他"
        assert change.after_category == "餐饮"


def test_rule_apply_confirmed_reports_scan_limit(client: TestClient, *, identity) -> None:
    for index in range(2):
        insert_confirmed_expense(
            amount_cents=4200,
            merchant=f"LimitCafe {index}",
            category="其他",
            expense_time=datetime(2026, 5, 5, 12, index, tzinfo=UTC),
            confirmed_at=datetime(2026, 5, 5, 12, index, tzinfo=UTC),
        )
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "LimitCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200

    preview = client.post("/api/rules/apply-confirmed?max_scan=1&limit=1", headers=identity.app_headers)
    first_apply = client.post(
        "/api/rules/apply-confirmed?max_scan=1",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": preview.json()["preview_token"]},
    )
    second_preview = client.post("/api/rules/apply-confirmed?max_scan=1&limit=1", headers=identity.app_headers)
    second_apply = client.post(
        "/api/rules/apply-confirmed?max_scan=1",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": second_preview.json()["preview_token"]},
    )

    assert preview.status_code == 200
    assert preview.json()["scan_limit"] == 1
    assert preview.json()["scan_limit_reached"] is True
    assert preview.json()["confirmed_scanned"] == 1
    assert first_apply.status_code == 200
    assert first_apply.json()["scan_limit_reached"] is True
    assert first_apply.json()["changed_count"] == 1
    assert second_preview.status_code == 200
    assert second_apply.status_code == 200
    assert second_apply.json()["scan_limit_reached"] is False
    assert second_apply.json()["changed_count"] == 1


def test_rule_apply_confirmed_rejects_stale_preview_token(client: TestClient, *, identity) -> None:
    confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="StalePreviewCafe",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "StalePreviewCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    preview = client.post("/api/rules/apply-confirmed", headers=identity.app_headers)
    assert preview.status_code == 200
    token = preview.json()["preview_token"]

    changed_rule = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=identity.app_headers,
        json={"category": "交通"},
    )
    assert changed_rule.status_code == 200

    stale_apply = client.post(
        "/api/rules/apply-confirmed",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": token},
    )
    assert stale_apply.status_code == 409
    assert stale_apply.json()["error"] == "preview_stale"
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        assert expense is not None
        assert expense.category == "其他"

    fresh_preview = client.post("/api/rules/apply-confirmed", headers=identity.app_headers)
    fresh_apply = client.post(
        "/api/rules/apply-confirmed",
        headers=identity.app_headers,
        json={"confirm": True, "preview_token": fresh_preview.json()["preview_token"]},
    )
    assert fresh_apply.status_code == 200
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == confirmed_id))
        assert expense is not None
        assert expense.category == "交通"


def test_rule_apply_confirmed_viewer_denied_and_cross_ledger_isolated(
    client: TestClient, *, identity,
) -> None:
    owner_confirmed_id = insert_confirmed_expense(
        amount_cents=4200,
        merchant="ConfirmedGuardCafe",
        category="其他",
        expense_time=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC),
    )
    when = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        db.add(
            Expense(
                tenant_id="tester_1",
                amount_cents=4200,
                merchant="ConfirmedGuardCafe",
                category="其他",
                note="",
                source="pytest",
                status="confirmed",
                expense_time=when,
                created_at=when,
                updated_at=when,
                confirmed_at=when,
            )
        )
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()

    owner_rule = client.post(
        "/api/rules/categories",
        headers=identity.gray_app_headers,
        json={"keyword": "ConfirmedGuardCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert owner_rule.status_code == 200

    owner_denied = client.post(
        "/api/rules/apply-confirmed",
        headers=identity.app_headers,
        json={"confirm": True},
    )
    tester_preview = client.post("/api/rules/apply-confirmed", headers=identity.gray_app_headers)
    assert tester_preview.status_code == 200
    tester_apply = client.post(
        "/api/rules/apply-confirmed",
        headers=identity.gray_app_headers,
        json={"confirm": True, "preview_token": tester_preview.json()["preview_token"]},
    )

    assert owner_denied.status_code == 403
    assert owner_denied.json()["error"] == "permission_denied"
    assert tester_apply.status_code == 200
    assert tester_apply.json()["changed_count"] == 1
    with SessionLocal() as db:
        owner_expense = db.scalar(select(Expense).where(Expense.id == owner_confirmed_id))
        assert owner_expense is not None
        assert owner_expense.category == "其他"
