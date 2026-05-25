"""v1.2 ops — cross-tenant isolation on maintenance endpoints.

Codex flagged on PR #124: the v1.2 maintenance route handlers
discarded ``auth`` and aggregated / cleaned globally, leaking other
tenants' table volume and even mutating their learning rows. These
tests pin down the fix.

Two surfaces:

* ``GET /api/maintenance/learning-status`` — counts must cover only
  the admin's tenant.
* ``POST /api/maintenance/cleanup-learning`` — sweep / prune must
  only touch the admin's tenant's rows.

The conftest seeds two tenants ("owner" and "tester_1"). The owner
admin token can only see / mutate owner-scoped data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, Expense, LedgerLearningEvent
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    get_status_overview,
    record_decision,
    record_event,
    run_full_maintenance,
)


def _seed_decision_in(tenant_id: str, *, retention_days: int = 30) -> int:
    now = datetime.now(UTC) - timedelta(days=200)
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id=tenant_id,
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=1,
                payload={"category": "餐饮"},
            ),
            now=now,
        )
        # Make it eligible for cleanup straight away.
        row.status = "dismissed"
        row.retention_days = retention_days
        db.commit()
        return row.id


def test_status_overview_scoped_by_tenant(*, identity) -> None:
    """``get_status_overview(tenant_id=...)`` returns per-tenant
    counts; passing the wrong tenant doesn't see other tenants'
    rows."""

    _seed_decision_in("owner")
    _seed_decision_in("tester_1")
    with SessionLocal() as db:
        owner_view = get_status_overview(db, tenant_id="owner")
        tester_view = get_status_overview(db, tenant_id="tester_1")
        assert owner_view.algorithm_decisions.total_rows == 1
        assert tester_view.algorithm_decisions.total_rows == 1
        # Each tenant only sees its own row, not the other tenant's.
        # Without the tenant_id scoping (the pre-fix global path),
        # both would have shown 2.


def test_status_endpoint_only_returns_admin_tenant_rows(
    client: TestClient, *, identity,
) -> None:
    _seed_decision_in("owner")
    _seed_decision_in("tester_1")
    # The admin_headers fixture is the owner's admin token.
    response = client.get(
        "/api/maintenance/learning-status",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    # Only owner's one row, not the global 2-row count.
    assert body["algorithm_decisions"]["total_rows"] == 1


def test_cleanup_endpoint_does_not_touch_other_tenants(
    client: TestClient, *, identity,
) -> None:
    """If the admin endpoint ran globally (the pre-fix bug), the
    tester_1 expired row would also get deleted. The fix is that
    the route passes auth.tenant_id, so only owner's row goes."""

    owner_decision_id = _seed_decision_in("owner", retention_days=30)
    tester_decision_id = _seed_decision_in("tester_1", retention_days=30)

    response = client.post(
        "/api/maintenance/cleanup-learning",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        owner_row = db.get(AlgorithmDecision, owner_decision_id)
        tester_row = db.get(AlgorithmDecision, tester_decision_id)
        # owner's row was deleted (expired + dismissed + retention=30);
        # tester_1's row is intact.
        assert owner_row is None
        assert tester_row is not None
        assert tester_row.tenant_id == "tester_1"


def test_status_endpoint_unauthorized_returns_401(
    client: TestClient, *, identity,
) -> None:
    """Sanity: no admin token → 401, not silent allow-through."""

    response = client.get("/api/maintenance/learning-status")
    assert response.status_code == 401


def test_run_full_maintenance_only_sweeps_named_tenant(*, identity) -> None:
    """Direct service-layer test: sweep / cleanup do not cross
    tenant boundary when tenant_id is explicit."""

    # Seed two active decisions whose expense is "confirmed" (stale
    # active), one in each tenant. Calling run_full_maintenance with
    # tenant_id='owner' must only close the owner's row.
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for tenant in ("owner", "tester_1"):
            expense = Expense(
                tenant_id=tenant,
                amount_cents=1000,
                merchant="m",
                category="其他",
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=now,
                confirmed_at=now,
            )
            db.add(expense)
            db.flush()
            record_decision(
                db,
                DecisionDraft(
                    tenant_id=tenant,
                    decision_type="category_suggestion",
                    algorithm_version="category-history-v1",
                    subject_kind="expense",
                    subject_id=expense.id,
                    payload={"category": "餐饮"},
                ),
            )
        db.commit()

        result = run_full_maintenance(db, tenant_id="owner")
        # The owner expense's active row got swept to dismissed; the
        # tester_1 expense's active row stayed active.
        assert result.swept_stale_active == 1

        active_remaining = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.status == "active")
            .all()
        )
        assert len(active_remaining) == 1
        assert active_remaining[0].tenant_id == "tester_1"


def test_scheduler_path_still_runs_globally(*, identity) -> None:
    """The cron / scheduler legitimately needs to sweep every tenant.
    ``run_full_maintenance(db)`` with no tenant_id stays global —
    that's the only legitimate global caller now."""

    now = datetime.now(UTC)
    with SessionLocal() as db:
        for tenant in ("owner", "tester_1"):
            expense = Expense(
                tenant_id=tenant,
                amount_cents=1000,
                merchant="m",
                category="其他",
                source="pytest",
                raw_text="",
                status="confirmed",
                expense_time=now,
                confirmed_at=now,
            )
            db.add(expense)
            db.flush()
            record_decision(
                db,
                DecisionDraft(
                    tenant_id=tenant,
                    decision_type="category_suggestion",
                    algorithm_version="category-history-v1",
                    subject_kind="expense",
                    subject_id=expense.id,
                    payload={"category": "餐饮"},
                ),
            )
        db.commit()

        result = run_full_maintenance(db)  # tenant_id defaults to None
        # Global sweep — both rows closed.
        assert result.swept_stale_active == 2


def test_event_count_scoped_by_tenant(*, identity) -> None:
    """Status overview also covers events; same isolation rule."""

    with SessionLocal() as db:
        for tenant in ("owner", "tester_1"):
            record_event(
                db,
                EventDraft(
                    tenant_id=tenant,
                    event_type="manual_override",
                    subject_kind="expense",
                    subject_id=1,
                ),
            )
        db.commit()
        owner = get_status_overview(db, tenant_id="owner")
        tester = get_status_overview(db, tenant_id="tester_1")
        assert owner.ledger_learning_events.total_rows == 1
        assert tester.ledger_learning_events.total_rows == 1
