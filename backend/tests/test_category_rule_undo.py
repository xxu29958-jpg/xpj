"""ADR-0038 undo for category_rules (soft-delete + restore).

DELETE now soft-deletes (sets ``deleted_at``); the row is hidden from every
read — the rule list, the classifier matcher, and the apply/preview engines —
but recoverable via ``POST /api/rules/categories/{id}/undo`` until cleanup
purges it past the retention window. The most important guarantee is the
classifier one: a soft-deleted rule must stop matching immediately.

Unlike merchant_alias, category_rules has no unique constraint, so undo can
never collide with a live row.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import SessionLocal
from app.models import CategoryRule, Expense
from app.services.cleanup_service import purge_expired_soft_deletes
from app.services.rule_service import classify_expense
from app.services.time_service import now_utc

# A keyword no DEFAULT_RULES entry contains, so matches are unambiguously ours.
_KW = "ZqUndoMart"


def _create_rule(client: TestClient, *, identity, keyword: str = _KW) -> dict:
    resp = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={"keyword": keyword, "category": "餐饮", "enabled": True, "priority": 1},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _soft_delete(client: TestClient, *, identity, rule: dict) -> None:
    resp = client.request(
        "DELETE",
        f"/api/rules/categories/{rule['id']}",
        headers=identity.app_headers,
        json={"expected_updated_at": rule["updated_at"]},
    )
    assert resp.status_code == 200, resp.text


def _classify_merchant(merchant: str) -> str:
    """Run the classifier over a fresh expense and return the category it lands."""
    now = now_utc()
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            status="pending",
            amount_cents=5_000,
            home_currency_code="CNY",
            original_currency_code="CNY",
            original_amount_minor=5_000,
            merchant=merchant,
            category="购物",  # distinct sentinel; the餐饮 rule would overwrite it
            expense_time=now,
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.flush()
        classify_expense(db, expense)
        return expense.category


def test_delete_soft_deletes_and_hides_from_list(client: TestClient, *, identity) -> None:
    rule = _create_rule(client, identity=identity)
    _soft_delete(client, identity=identity, rule=rule)

    listing = client.get("/api/rules/categories", headers=identity.app_headers)
    assert listing.status_code == 200
    assert all(r["id"] != rule["id"] for r in listing.json())

    # The row still physically exists — soft, not hard, delete.
    with SessionLocal() as db:
        row = db.get(CategoryRule, rule["id"])
        assert row is not None
        assert row.deleted_at is not None


def test_soft_deleted_rule_stops_classifying(client: TestClient, *, identity) -> None:
    # The correctness landmine: a soft-deleted rule must not match.
    rule = _create_rule(client, identity=identity)
    assert _classify_merchant(f"{_KW} Downtown") == "餐饮"  # live rule matches

    _soft_delete(client, identity=identity, rule=rule)
    assert _classify_merchant(f"{_KW} Uptown") == "购物"  # ignored after delete


def test_undo_restores_rule_and_writes_audit(client: TestClient, *, identity) -> None:
    rule = _create_rule(client, identity=identity)
    _soft_delete(client, identity=identity, rule=rule)

    undo = client.post(
        f"/api/rules/categories/{rule['id']}/undo", headers=identity.app_headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["id"] == rule["id"]

    # Restored: visible again and classifying again.
    listing = client.get("/api/rules/categories", headers=identity.app_headers)
    assert any(r["id"] == rule["id"] for r in listing.json())
    assert _classify_merchant(f"{_KW} Eastside") == "餐饮"

    with SessionLocal() as db:
        row = db.get(CategoryRule, rule["id"])
        assert row is not None and row.deleted_at is None
        audit_rows = db.execute(
            text(
                "SELECT COUNT(*) FROM ledger_audit_logs "
                "WHERE action = 'undo' AND resource_type = 'category_rule' "
                "AND resource_public_id = :rid"
            ),
            {"rid": str(rule["id"])},
        ).scalar()
        assert audit_rows == 1


def test_undo_live_or_missing_rule_returns_404(client: TestClient, *, identity) -> None:
    # A live (never-deleted) rule has nothing to undo.
    rule = _create_rule(client, identity=identity, keyword=f"{_KW}Live")
    resp = client.post(
        f"/api/rules/categories/{rule['id']}/undo", headers=identity.app_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "rule_not_found"

    missing = client.post(
        "/api/rules/categories/99999999/undo", headers=identity.app_headers
    )
    assert missing.status_code == 404


def test_purge_removes_soft_deleted_past_retention(client: TestClient, *, identity) -> None:
    rule = _create_rule(client, identity=identity, keyword=f"{_KW}Purge")
    _soft_delete(client, identity=identity, rule=rule)

    with SessionLocal() as db:
        # Inside the window: not purged.
        assert purge_expired_soft_deletes(db, retention_minutes=5) == 0
        assert db.get(CategoryRule, rule["id"]) is not None
        # Past the window: purged for good.
        future = now_utc() + timedelta(minutes=10)
        purged = purge_expired_soft_deletes(db, retention_minutes=5, now=future)
        assert purged >= 1
        assert db.get(CategoryRule, rule["id"]) is None

    # Undo after purge is a 404 — the row is gone.
    resp = client.post(
        f"/api/rules/categories/{rule['id']}/undo", headers=identity.app_headers
    )
    assert resp.status_code == 404


def test_undo_requires_auth(client: TestClient, *, identity) -> None:  # noqa: ARG001
    # Unauthenticated undo is rejected before touching the row (401 gate).
    resp = client.post("/api/rules/categories/1/undo")
    assert resp.status_code == 401, resp.text
