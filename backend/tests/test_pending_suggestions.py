from __future__ import annotations

import json

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
            "amount_cents": 1200 + day,
            "merchant": merchant,
            "category": category,
            "spent_at": f"2026-05-{day:02d}T03:00:00Z",
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
            "amount_cents": 1888,
            "merchant": merchant,
            "category": "其他",
            "spent_at": "2026-05-10T03:00:00Z",
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
