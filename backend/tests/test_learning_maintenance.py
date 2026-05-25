"""v1.2 ops — maintenance endpoints + status overview + last_run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.models.app_meta import LEARNING_CLEANUP_LAST_RUN_KEY
from app.routes.owner_console import _require_local
from app.services.app_meta_service import get_value
from app.services.learning_service import (
    DecisionDraft,
    EventDraft,
    get_status_overview,
    record_decision,
    record_event,
    run_full_maintenance,
)


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """Bypass Owner Console loopback gate for the test."""

    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def _seed_active_decision(*, retention_days: int = 30, days_ago: int = 0) -> int:
    now = datetime.now(UTC) - timedelta(days=days_ago)
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=1,
                payload={"category": "餐饮"},
            ),
            now=now,
        )
        row.retention_days = retention_days
        db.commit()
        return row.id


def _seed_pending_expense() -> int:
    with SessionLocal() as db:
        expense = Expense(
            tenant_id="owner",
            amount_cents=1000,
            merchant="m",
            category="其他",
            source="pytest",
            raw_text="",
            status="pending",
            expense_time=datetime.now(UTC),
        )
        db.add(expense)
        db.commit()
        return expense.id


def test_status_overview_reflects_counts(*, identity) -> None:
    # One active decision + one expired ledger event.
    _seed_active_decision(retention_days=180, days_ago=0)
    with SessionLocal() as db:
        old_event = record_event(
            db,
            EventDraft(
                tenant_id="owner",
                event_type="manual_override",
                subject_kind="expense",
                subject_id=1,
            ),
            now=datetime.now(UTC) - timedelta(days=200),
        )
        old_event.retention_days = 30
        db.commit()

        overview = get_status_overview(db)
        assert overview.algorithm_decisions.total_rows == 1
        assert overview.active_decisions == 1
        assert overview.ledger_learning_events.total_rows == 1
        assert overview.ledger_learning_events.expired_candidate_rows == 1
        assert overview.last_cleanup_at is None


def test_status_overview_counts_stale_active_candidates(*, identity) -> None:
    # Active decision attached to a confirmed expense is "stale active"
    # and gets surfaced separately so Owner Console can flag it.
    expense_id = _seed_pending_expense()
    with SessionLocal() as db:
        row = record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=expense_id,
                payload={"category": "餐饮"},
            ),
        )
        # Flip the expense to confirmed without going through the
        # confirm_expense service — simulates a path that bypassed the
        # explicit close.
        expense = db.get(Expense, expense_id)
        expense.status = "confirmed"
        expense.confirmed_at = datetime.now(UTC)
        db.commit()

        overview = get_status_overview(db)
        assert overview.active_decisions == 1
        assert overview.stale_active_candidates == 1


def test_run_full_maintenance_returns_elapsed_and_summary(
    *, identity,
) -> None:
    """elapsed_ms is wall-clock; summary lands in app_meta so Owner
    Console can show "last cleanup took N ms" without a separate
    audit table."""

    import json

    from app.models.app_meta import LEARNING_CLEANUP_LAST_SUMMARY_KEY

    with SessionLocal() as db:
        result = run_full_maintenance(db)
        assert result.elapsed_ms >= 0

        raw = get_value(db, LEARNING_CLEANUP_LAST_SUMMARY_KEY)
        assert raw is not None
        summary = json.loads(raw)
        assert summary["elapsed_ms"] == result.elapsed_ms
        assert summary["total_deleted"] == 0
        assert summary["finished_at"] == result.finished_at
        # Owner Console reads the same summary off get_status_overview.
        from app.services.learning_service import get_status_overview

        overview = get_status_overview(db)
        assert overview.last_cleanup_summary == summary


def test_run_full_maintenance_sweeps_and_stamps(*, identity) -> None:
    expense_id = _seed_pending_expense()
    with SessionLocal() as db:
        record_decision(
            db,
            DecisionDraft(
                tenant_id="owner",
                decision_type="category_suggestion",
                algorithm_version="category-history-v1",
                subject_kind="expense",
                subject_id=expense_id,
                payload={"category": "餐饮"},
            ),
        )
        expense = db.get(Expense, expense_id)
        expense.status = "confirmed"
        expense.confirmed_at = datetime.now(UTC)
        db.commit()

        result = run_full_maintenance(db)
        assert result.swept_stale_active == 1
        # The just-closed row is now eligible for retention cleanup
        # — though it was created at "now" so retention hasn't
        # elapsed; assert at least the swept count for now.
        assert result.finished_at  # ISO string

        # The app_meta stamp landed.
        stamp = get_value(db, LEARNING_CLEANUP_LAST_RUN_KEY)
        assert stamp == result.finished_at


def test_maintenance_route_returns_status(
    client: TestClient, *, identity
) -> None:
    response = client.get(
        "/api/maintenance/learning-status",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert "algorithm_decisions" in body
    assert "ledger_learning_events" in body
    assert "ocr_facts" in body
    assert body["last_cleanup_at"] is None


def test_maintenance_route_runs_cleanup(
    client: TestClient, *, identity
) -> None:
    response = client.post(
        "/api/maintenance/cleanup-learning",
        headers=identity.admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "cleanup" in body
    assert "finished_at" in body
    # Re-query status; last_cleanup_at must now be populated.
    status = client.get(
        "/api/maintenance/learning-status",
        headers=identity.admin_headers,
    )
    assert status.json()["last_cleanup_at"] == body["finished_at"]


def test_cleanup_learning_rejects_unauth(
    client: TestClient, *, identity
) -> None:
    """/api/maintenance/cleanup-learning is admin-only; no token → 401."""

    response = client.post("/api/maintenance/cleanup-learning")
    assert response.status_code == 401


def test_owner_console_panel_renders(
    local_client: TestClient, *, identity
) -> None:
    response = local_client.get("/owner/learning-maintenance")
    assert response.status_code == 200
    text = response.text
    assert "学习层维护" in text
    assert "algorithm_decisions" in text
    assert "ledger_learning_events" in text
    assert "ocr_facts" in text
    # Display labels from the registry.
    assert "分类建议" in text
    assert "疑似重复" in text
    assert "预算建议" in text


def test_owner_console_panel_run_redirects(
    local_client: TestClient, *, identity
) -> None:
    response = local_client.post(
        "/owner/learning-maintenance/run", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/owner/learning-maintenance"


def test_owner_console_lists_active_decisions(
    local_client: TestClient, *, identity
) -> None:
    """Active rows show up in the dismiss table so the owner has
    something concrete to click."""

    _seed_active_decision(retention_days=180)

    response = local_client.get("/owner/learning-maintenance")
    assert response.status_code == 200
    text = response.text
    assert "active 决策" in text
    assert "category_suggestion" in text
    assert "Dismiss" in text


def test_owner_console_dismiss_flips_active_row(
    local_client: TestClient, *, identity
) -> None:
    from app.models import AlgorithmDecision

    _seed_active_decision(retention_days=180)
    with SessionLocal() as db:
        decision = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.status == "active")
            .one()
        )
        public_id = decision.public_id

    response = local_client.post(
        "/owner/learning-maintenance/dismiss-decision",
        data={"decision_public_id": public_id},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/owner/learning-maintenance"

    with SessionLocal() as db:
        row = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.public_id == public_id)
            .one()
        )
        assert row.status == "dismissed"


def test_owner_console_dismiss_silently_ignores_unknown(
    local_client: TestClient, *, identity
) -> None:
    """Race condition: cleanup pruned the row between page render
    and click. Dismiss must redirect cleanly, not 404."""

    response = local_client.post(
        "/owner/learning-maintenance/dismiss-decision",
        data={"decision_public_id": "00000000-0000-0000-0000-000000000000"},
        follow_redirects=False,
    )
    assert response.status_code == 303
