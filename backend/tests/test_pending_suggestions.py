from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import AlgorithmDecision, LedgerLearningEvent
from tests._infra.assets import PNG_BYTES


def _confirmed(
    client: TestClient,
    *,
    identity,
    merchant: str,
    category: str,
    day: int,
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 1200 + day,
            "merchant": merchant,
            "category": category,
            "spent_at": (datetime.now(UTC) - timedelta(days=day)).isoformat(),
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _pending_notification(client: TestClient, *, identity, merchant: str) -> int:
    response = client.post(
        "/api/expenses/notification-drafts",
        headers=identity.app_headers,
        json={
            "source": "alipay",
            "notification_key": str(uuid4()),
            "amount_cents": 1888,
            "merchant": merchant,
            "category": "其他",
            "spent_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def test_pending_api_returns_category_suggestion_and_reuses_decision(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="全家便利店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(
        client, identity=identity, merchant="全家便利店"
    )

    first = client.get("/api/expenses/pending", headers=identity.app_headers)
    second = client.get("/api/expenses/pending", headers=identity.app_headers)

    assert first.status_code == 200, first.json()
    assert second.status_code == 200, second.json()
    item = next(row for row in first.json() if row["id"] == pending_id)
    suggestion = item["category_suggestion"]
    assert suggestion["category"] == "餐饮"
    assert suggestion["sample_size"] == 3
    assert suggestion["decision_public_id"]
    assert item["duplicate_candidates"] == []

    with SessionLocal() as db:
        count = (
            db.query(AlgorithmDecision)
            .filter(AlgorithmDecision.tenant_id == "owner")
            .filter(AlgorithmDecision.subject_id == pending_id)
            .filter(AlgorithmDecision.decision_type == "category_suggestion")
            .count()
        )
    assert count == 1


def test_pending_api_returns_duplicate_candidate(client: TestClient, *, identity) -> None:
    first = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("first.png", PNG_BYTES, "image/png")},
    )
    second = client.post(
        identity.upload_url_path,
        headers=identity.upload_headers,
        files={"file": ("second.png", PNG_BYTES, "image/png")},
    )
    assert first.status_code == 200, first.json()
    assert second.status_code == 200, second.json()

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    item = next(row for row in pending.json() if row["id"] == second.json()["id"])
    candidates = item["duplicate_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["candidate_id"] == first.json()["id"]
    assert candidates[0]["score"] >= 0.5
    assert "image_hash_match" in candidates[0]["reasons"]
    assert candidates[0]["decision_public_id"]


def test_pending_suggestion_accept_and_reject_write_learning_events(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="咖啡小店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(client, identity=identity, merchant="咖啡小店")
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    decision_public_id = next(
        row for row in pending.json() if row["id"] == pending_id
    )["category_suggestion"]["decision_public_id"]

    accepted = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.app_headers,
    )
    rejected = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/reject",
        headers=identity.app_headers,
    )

    assert accepted.status_code == 200, accepted.json()
    assert rejected.status_code == 200, rejected.json()
    with SessionLocal() as db:
        rows = (
            db.query(LedgerLearningEvent)
            .filter(LedgerLearningEvent.tenant_id == "owner")
            .filter(LedgerLearningEvent.subject_id == pending_id)
            .order_by(LedgerLearningEvent.id.asc())
            .all()
        )
    assert [row.event_type for row in rows] == ["accept", "reject"]
    assert json.loads(rows[-1].before_payload or "{}") == {"category": "餐饮"}


def test_pending_suggestion_feedback_is_tenant_scoped(
    client: TestClient, *, identity
) -> None:
    for day in (1, 2, 3):
        _confirmed(
            client,
            identity=identity,
            merchant="租户隔离店",
            category="餐饮",
            day=day,
        )
    pending_id = _pending_notification(client, identity=identity, merchant="租户隔离店")
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    decision_public_id = next(
        row for row in pending.json() if row["id"] == pending_id
    )["category_suggestion"]["decision_public_id"]

    blocked = client.post(
        f"/api/expenses/{pending_id}/suggestions/{decision_public_id}/accept",
        headers=identity.gray_app_headers,
    )

    assert blocked.status_code == 404


def test_pending_feedback_rejects_unknown_decision(
    client: TestClient, *, identity
) -> None:
    pending_id = _pending_notification(client, identity=identity, merchant="无建议店")
    response = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/reject",
        headers=identity.app_headers,
    )
    assert response.status_code == 404


def test_pending_suggestion_feedback_requires_auth(client: TestClient, *, identity) -> None:
    pending_id = _pending_notification(client, identity=identity, merchant="鉴权店")

    accept = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/accept"
    )
    reject = client.post(
        f"/api/expenses/{pending_id}/suggestions/not-a-decision/reject"
    )

    assert accept.status_code == 401
    assert reject.status_code == 401


def test_feedback_changes_the_next_real_review_without_changing_money(client, web_client, identity):
    """Read -> correct -> reopen -> next receipt, across the actual consumers."""
    from api_contract_helpers import patch_expense

    from app.models import Expense

    for day in (1, 2, 3):
        _confirmed(client, identity=identity, merchant="学习咖啡店", category="餐饮", day=day)
    pending_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    detail = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers).json()
    suggestion = detail["category_suggestion"]
    assert suggestion and suggestion["category"] == "餐饮"
    page = web_client.get(f"/web/expenses/{pending_id}/edit?ledger_id=owner")
    assert 'data-category-suggestion="餐饮"' in page.text
    assert "3 笔" in page.text

    intervening = patch_expense(client, pending_id, headers=identity.app_headers, fields={"note": "另一端刚保存"})
    assert intervening.status_code == 200
    stale = client.patch(f"/api/expenses/{pending_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"category": "购物", "expected_row_version": detail["row_version"]})
    assert stale.status_code == 409
    with SessionLocal() as db:
        assert db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id == pending_id).count() == 0

    changed = patch_expense(client, pending_id, headers=identity.app_headers, fields={"category": "购物"})
    assert changed.status_code == 200, changed.text
    # A stored feedback row alone is not the outcome: reopening must honour it.
    reopened = client.get(f"/api/expenses/{pending_id}", headers=identity.app_headers).json()
    assert reopened["category_suggestion"] is None
    assert reopened["category"] == "购物" and reopened["amount_cents"] == 1888

    second_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    second = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert second_id != pending_id, second
    assert second["category_suggestion"] is not None, second
    decision_id = second["category_suggestion"]["decision_public_id"]
    rejected = client.post(f"/api/expenses/{second_id}/suggestions/{decision_id}/reject", headers=identity.app_headers)
    assert rejected.status_code == 200
    third_id = _pending_notification(client, identity=identity, merchant="学习咖啡店")
    third = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert third["category_suggestion"] is None  # Two corrections suppress the same merchant/category.
    with SessionLocal() as db:
        assert db.get(Expense, third_id).category == "其他"
        assert db.get(Expense, third_id).amount_cents == 1888
        events = db.query(LedgerLearningEvent).filter(LedgerLearningEvent.subject_id.in_([pending_id, second_id])).all()
        assert [e.event_type for e in sorted(events, key=lambda e: e.id)] == ["reject", "reject"]


def test_keep_both_changes_future_duplicate_evidence_and_preserves_both_bills(client, web_client, identity):
    from api_contract_helpers import mark_not_duplicate_api
    from sqlalchemy import event

    first_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    second_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    before = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert before["duplicate_candidates"]
    original_score = before["duplicate_candidates"][0]["score"]
    kept = mark_not_duplicate_api(client, second_id, headers=identity.app_headers)
    assert kept.status_code == 200, kept.text
    third_id = _pending_notification(client, identity=identity, merchant="重复核对店")
    after = client.get(f"/api/expenses/{third_id}", headers=identity.app_headers).json()
    assert after["duplicate_candidates"][0]["score"] < original_score
    assert "recent_user_reject" in after["duplicate_candidates"][0]["reasons"]
    for _ in range(2):
        _pending_notification(client, identity=identity, merchant="重复核对店")
    feedback_queries = []

    def capture_feedback_query(conn, cursor, statement, parameters, context, executemany):
        if "ledger_learning_events" in statement and "signal_hash" in statement:
            feedback_queries.append(statement)

    with SessionLocal() as db:
        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", capture_feedback_query)
        try:
            page = web_client.get("/web/duplicates?ledger_id=owner")
        finally:
            event.remove(engine, "before_cursor_execute", capture_feedback_query)
    assert len(feedback_queries) == 1  # The whole review page shares one indexed feedback read.
    assert "已参考你之前“不是重复”的选择" in page.text
    for expense_id in (first_id, second_id):
        expense = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
        assert expense["amount_cents"] == 1888 and expense["status"] == "pending"
