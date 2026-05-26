from __future__ import annotations

from api_contract_helpers import (
    upload_png,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import DuplicateIgnore
from app.services.duplicate_service import _remember_duplicate_ignore


def test_duplicate_detection_never_rejects_or_confirms(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    matched = next(item for item in pending.json() if item["id"] == second_id)
    assert matched["duplicate_status"] == "suspected"
    assert matched["duplicate_of_id"] == first_id
    assert matched["status"] == "pending"
    assert matched["confirmed_at"] is None
    assert matched["rejected_at"] is None


def test_mark_not_duplicate_suppresses_all_current_pair_detection_types(
    client: TestClient, *, identity,
) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)

    response = client.post(
        f"/api/expenses/{second_id}/mark-not-duplicate", headers=identity.app_headers
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = client.patch(
            f"/api/expenses/{expense_id}",
            headers=identity.app_headers,
            json={
                "amount_cents": 5200,
                "merchant": "同一家店",
                "category": "生活",
                "expense_time": timestamp,
            },
        )
        assert response.status_code == 200

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    matched = next(item for item in pending.json() if item["id"] == second_id)
    assert matched["status"] == "pending"
    assert matched["duplicate_status"] == "none"
    assert matched["duplicate_of_id"] is None


def test_duplicate_ignore_insert_is_idempotent_for_retries(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)

    with SessionLocal() as db:
        _remember_duplicate_ignore(db, "owner", second_id, first_id, "similar")
        _remember_duplicate_ignore(db, "owner", second_id, first_id, "similar")
        db.commit()

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(DuplicateIgnore)
            .where(DuplicateIgnore.tenant_id == "owner")
            .where(DuplicateIgnore.kind == "similar")
        )
    assert count == 1


def test_duplicate_and_category_rule_contract(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)

    duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    assert duplicates.status_code == 200
    assert any(item["id"] == second_id for item in duplicates.json())

    response = client.post(f"/api/expenses/{second_id}/reject", headers=identity.app_headers)
    assert response.status_code == 200
    duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    assert duplicates.status_code == 200
    assert all(item["id"] != second_id for item in duplicates.json())

    second_id = upload_png(client, identity=identity)
    duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    assert duplicates.status_code == 200
    assert any(item["id"] == second_id for item in duplicates.json())

    response = client.post(
        f"/api/expenses/{second_id}/mark-not-duplicate", headers=identity.app_headers
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    response = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "测试商家",
            "category": "生活",
            "enabled": True,
            "priority": 1,
        },
    )
    assert response.status_code == 200
    rule_id = int(response.json()["id"])

    created_rule = response.json()
    response = client.patch(
        f"/api/rules/categories/{rule_id}",
        headers=identity.app_headers,
        json={
            "priority": 2,
            "enabled": False,
            "expected_updated_at": created_rule["updated_at"],
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 2
    assert response.json()["enabled"] is False

    response = client.request(
        "DELETE",
        f"/api/rules/categories/{rule_id}",
        headers=identity.app_headers,
        json={"expected_updated_at": response.json()["updated_at"]},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    reject = client.post(f"/api/expenses/{first_id}/reject", headers=identity.app_headers)
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


def test_similar_expense_duplicate_ignore_survives_after_edit(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)
    client.post(f"/api/expenses/{second_id}/mark-not-duplicate", headers=identity.app_headers)

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = client.patch(
            f"/api/expenses/{expense_id}",
            headers=identity.app_headers,
            json={
                "amount_cents": 5200,
                "merchant": "同一家店",
                "category": "生活",
                "expense_time": timestamp,
            },
        )
        assert response.status_code == 200

    second = client.get("/api/expenses/pending", headers=identity.app_headers).json()
    matched = next(item for item in second if item["id"] == second_id)
    assert matched["duplicate_status"] == "none"
    assert matched["duplicate_of_id"] is None


def test_editing_duplicate_original_revalidates_stale_references(client: TestClient, *, identity) -> None:
    first = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 5200,
            "merchant": "Same Store",
            "category": "生活",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert first.status_code == 200, first.json()
    first_id = first.json()["id"]
    second = client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 5200,
            "merchant": "Same Store",
            "category": "生活",
            "expense_time": "2026-05-03T05:20:00Z",
        },
    )
    assert second.status_code == 200, second.json()
    second_id = second.json()["id"]
    assert second.json()["duplicate_of_id"] == first_id

    response = client.patch(
        f"/api/expenses/{first_id}",
        headers=identity.app_headers,
        json={
            "amount_cents": 5200,
            "merchant": "Changed Original",
            "category": "生活",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert response.status_code == 200

    after = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers)
    assert after.status_code == 200
    assert after.json()["duplicate_status"] == "none"
    assert after.json()["duplicate_of_id"] is None
