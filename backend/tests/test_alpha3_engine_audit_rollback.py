"""v0.4-alpha3 Smart Ledger Engine — Rules preview/apply + Recurring candidates."""
from __future__ import annotations

from api_contract_helpers import patch_expense, upload_png
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CategoryRule, Expense, LedgerMember, RuleApplicationBatch, RuleApplicationChange
from app.services.rule_application_service import _try_apply_rule_category, _try_rollback_rule_change
from app.services.time_service import now_utc


def _seed_pending_with_merchant(merchant: str) -> int:
    """Upload a PNG (pending), then patch its merchant to control matching."""
    # Use a TestClient implicitly via the fixture in the test that calls this helper.
    raise RuntimeError("call _patch_pending_merchant from a test using `client`")


def _set_pending_merchant(client: TestClient, expense_id: int, merchant: str, *, identity) -> None:
    response = patch_expense(
        client,
        expense_id,
        headers=identity.app_headers,
        fields={"merchant": merchant, "amount_cents": 3800},
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


def test_rule_application_audit_and_rollback_integration(client: TestClient, *, identity) -> None:
    """Owner API flow: no-op creates no audit, real apply audits, rollback is idempotent."""
    upload_png(client, identity=identity)
    noop = _apply_pending_rules(client, identity=identity)
    assert noop.status_code == 200
    assert noop.json()["changed_count"] == 0
    assert client.get("/api/rules/applications", headers=identity.app_headers).json()["items"] == []

    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "AuditCafe 上海", identity=identity)
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "AuditCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    applied = _apply_pending_rules(client, identity=identity)
    assert applied.status_code == 200
    assert applied.json()["changed_count"] == 1

    listed = client.get("/api/rules/applications", headers=identity.app_headers)
    assert listed.status_code == 200
    batch_id = listed.json()["items"][0]["public_id"]
    assert listed.json()["items"][0]["status"] == "applied"
    with SessionLocal() as db:
        batch = db.scalar(select(RuleApplicationBatch).where(RuleApplicationBatch.public_id == batch_id))
        assert batch is not None
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
        assert change.before_category == "其他"
        assert change.after_category == "餐饮"

    rollback = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.app_headers)
    assert rollback.status_code == 200
    assert rollback.json()["changed"] == 1
    assert rollback.json()["skipped"] == 0
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "其他"

    second = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.app_headers)
    assert second.status_code == 200
    assert second.json()["changed"] == 0
    assert second.json()["skipped"] == 1


def test_rule_application_rollback_safety_boundaries_integration(client: TestClient, *, identity) -> None:
    """One integration path covers manual edits, cross-ledger hiding, and writer guard."""
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "BoundaryCafe", identity=identity)
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "BoundaryCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    _apply_pending_rules(client, identity=identity)
    batch_id = client.get("/api/rules/applications", headers=identity.app_headers).json()["items"][0]["public_id"]

    gray_list = client.get("/api/rules/applications", headers=identity.gray_app_headers)
    gray_rollback = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.gray_app_headers)
    assert gray_list.status_code == 200
    assert all(item["public_id"] != batch_id for item in gray_list.json()["items"])
    assert gray_rollback.status_code == 404

    manual = patch_expense(
        client,
        pending_id,
        headers=identity.app_headers,
        fields={"category": "交通"},
    )
    assert manual.status_code == 200
    skipped = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.app_headers)
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "rollback_skipped"
    assert skipped.json()["changed"] == 0
    assert skipped.json()["skipped"] == 1
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"

    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()
    response = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.app_headers)
    assert response.status_code == 403
    assert response.json()["error"] == "permission_denied"


def test_rule_application_rollback_skips_after_manual_edit_even_when_category_matches(
    client: TestClient, *, identity,
) -> None:
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "ManualEditCafe", identity=identity)
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "ManualEditCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    applied = _apply_pending_rules(client, identity=identity)
    assert applied.status_code == 200
    batch_id = client.get("/api/rules/applications", headers=identity.app_headers).json()["items"][0]["public_id"]

    manual = patch_expense(
        client,
        pending_id,
        headers=identity.app_headers,
        fields={"note": "用户后续手工编辑过备注"},
    )
    assert manual.status_code == 200, manual.json()
    assert manual.json()["category"] == "餐饮"

    rollback = client.post(f"/api/rules/applications/{batch_id}/rollback", headers=identity.app_headers)
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "rollback_skipped"
    assert rollback.json()["changed"] == 0
    assert rollback.json()["skipped"] == 1

    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "餐饮"
        assert expense.note == "用户后续手工编辑过备注"


def test_rule_application_cas_skips_stale_candidate_snapshot(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "RaceCafe", identity=identity)
    created = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "RaceCafe", "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert created.status_code == 200
    rule_id = created.json()["id"]

    with SessionLocal() as stale_db:
        stale_expense = stale_db.scalar(select(Expense).where(Expense.id == pending_id))
        stale_rule = stale_db.scalar(select(CategoryRule).where(CategoryRule.id == rule_id))
        assert stale_expense is not None
        assert stale_rule is not None
        assert stale_expense.category == "其他"
        stale_db.expunge(stale_expense)
        stale_db.expunge(stale_rule)

    with SessionLocal() as user_db:
        expense = user_db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        expense.category = "交通"
        expense.updated_at = now_utc()
        user_db.commit()

    with SessionLocal() as apply_db:
        applied = _try_apply_rule_category(
            apply_db,
            tenant_id="owner",
            status="pending",
            expense=stale_expense,
            rule=stale_rule,
            before_category="其他",
            after_category="餐饮",
            now=now_utc(),
        )
        apply_db.rollback()

    assert applied is None
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "交通"


def test_rule_application_rollback_cas_skips_stale_expense_snapshot(client: TestClient, *, identity) -> None:
    pending_id = upload_png(client, identity=identity)
    _set_pending_merchant(client, pending_id, "RollbackRaceCafe", identity=identity)
    client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": "RollbackRaceCafe", "category": "Food", "enabled": True, "priority": 1},
    )
    applied = _apply_pending_rules(client, identity=identity)
    assert applied.status_code == 200

    with SessionLocal() as stale_db:
        stale_expense = stale_db.scalar(select(Expense).where(Expense.id == pending_id))
        change = stale_db.scalar(
            select(RuleApplicationChange).where(RuleApplicationChange.expense_id == pending_id)
        )
        assert stale_expense is not None
        assert change is not None
        stale_db.expunge(stale_expense)
        stale_db.expunge(change)

    with SessionLocal() as user_db:
        expense = user_db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        expense.category = "Manual"
        expense.updated_at = now_utc()
        user_db.commit()

    with SessionLocal() as rollback_db:
        rolled_back = _try_rollback_rule_change(
            rollback_db,
            tenant_id="owner",
            expense=stale_expense,
            change=change,
            now=now_utc(),
        )
        rollback_db.rollback()

    assert rolled_back is False
    with SessionLocal() as db:
        expense = db.scalar(select(Expense).where(Expense.id == pending_id))
        assert expense is not None
        assert expense.category == "Manual"
