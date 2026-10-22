from __future__ import annotations

from uuid import uuid4

from api_contract_helpers import (
    mark_not_duplicate_api,
    patch_expense,
    reject_expense_api,
    upload_png,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AppMeta, DuplicateIgnore, Expense
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

    response = mark_not_duplicate_api(
        client, second_id, headers=identity.app_headers
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = patch_expense(
            client,
            expense_id,
            headers=identity.app_headers,
            fields={
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

    response = reject_expense_api(client, second_id, headers=identity.app_headers)
    assert response.status_code == 200
    duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    assert duplicates.status_code == 200
    assert all(item["id"] != second_id for item in duplicates.json())

    second_id = upload_png(client, identity=identity)
    duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    assert duplicates.status_code == 200
    assert any(item["id"] == second_id for item in duplicates.json())

    response = mark_not_duplicate_api(
        client, second_id, headers=identity.app_headers
    )
    assert response.status_code == 200
    assert response.json()["duplicate_status"] == "none"

    response = client.post(
        "/api/rules/categories",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
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
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "priority": 2,
            "enabled": False,
            "expected_row_version": created_rule["row_version"],
        },
    )
    assert response.status_code == 200
    assert response.json()["priority"] == 2
    assert response.json()["enabled"] is False

    response = client.request(
        "DELETE",
        f"/api/rules/categories/{rule_id}",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": response.json()["row_version"]},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    reject = reject_expense_api(client, first_id, headers=identity.app_headers)
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


def test_similar_expense_duplicate_ignore_survives_after_edit(client: TestClient, *, identity) -> None:
    first_id = upload_png(client, identity=identity)
    second_id = upload_png(client, identity=identity)
    mark_not_duplicate_api(client, second_id, headers=identity.app_headers)

    for expense_id, timestamp in [
        (first_id, "2026-05-03T04:20:00Z"),
        (second_id, "2026-05-03T05:20:00Z"),
    ]:
        response = patch_expense(
            client,
            expense_id,
            headers=identity.app_headers,
            fields={
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
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 5200,
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
            "client_ref": str(uuid4()),
            "home_currency_code": "CNY", "amount_cents": 5200,
            "merchant": "Same Store",
            "category": "生活",
            "expense_time": "2026-05-03T05:20:00Z",
        },
    )
    assert second.status_code == 200, second.json()
    second_id = second.json()["id"]
    assert second.json()["duplicate_of_id"] == first_id
    second_row_version = second.json()["row_version"]

    response = client.post(
        f"/api/expenses/{first_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": first.json()["row_version"],
            "reason": "原始记录商家录错",
            "amount_cents": 5200,
            "merchant": "Changed Original",
            "category": "生活",
            "expense_time": "2026-05-03T04:20:00Z",
        },
    )
    assert response.status_code == 201

    after = client.get(f"/api/expenses/{second_id}", headers=identity.app_headers)
    assert after.status_code == 200
    assert after.json()["duplicate_status"] == "none"
    assert after.json()["duplicate_of_id"] is None
    assert after.json()["row_version"] == second_row_version + 1


def test_legacy_visual_flag_reconciles_for_every_consumer_without_changing_money(web_client, monkeypatch, *, identity):
    import pytest

    from app.services import duplicate_service
    from app.services.currency_binding_service import authorize_currency_metadata_write
    from app.services.data_quality_service import data_quality_summary
    from app.services.duplicate_service import PROJECTION_VERSION_KEY, reconcile_legacy_duplicate_statuses
    from app.services.server_settings_service import server_settings_snapshot
    from app.services.web_stats_service import sidebar_counts

    first_id = upload_png(web_client, identity=identity)
    second_id = upload_png(web_client, identity=identity)
    for row_id, amount in ((first_id, 1851), (second_id, 2200)):
        changed = patch_expense(web_client, row_id, headers=identity.app_headers,
            fields={"amount_cents": amount, "merchant": "Legacy Store"})
        assert changed.status_code == 200
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        marker = db.get(AppMeta, PROJECTION_VERSION_KEY)
        if marker is not None:
            db.delete(marker)
        current = db.get(Expense, second_id)
        current.duplicate_status = "suspected"
        current.duplicate_of_id = first_id
        current.duplicate_reason = "图片相同"  # Persisted by the previous admission algorithm.
        db.commit()
        version = current.row_version
        untouched = {row.id: {column.name: getattr(row, column.name) for column in Expense.__table__.columns
            if column.name not in {"duplicate_status", "duplicate_of_id", "duplicate_reason", "row_version", "updated_at"}}
            for row in db.scalars(select(Expense).where(Expense.tenant_id == "owner"))}

    original = duplicate_service.mark_duplicate_status

    def interrupted(db, expense):
        original(db, expense)
        db.flush()
        raise RuntimeError("interrupted upgrade")

    with monkeypatch.context() as patcher:
        patcher.setattr(duplicate_service, "mark_duplicate_status", interrupted)
        with SessionLocal() as db, pytest.raises(RuntimeError, match="interrupted upgrade"):
            reconcile_legacy_duplicate_statuses(db)
    with SessionLocal() as db:
        assert db.get(AppMeta, PROJECTION_VERSION_KEY) is None
        assert db.get(Expense, second_id).duplicate_of_id == first_id
        assert db.get(Expense, second_id).row_version == version
        assert reconcile_legacy_duplicate_statuses(db) == 1
        db.commit()
        assert reconcile_legacy_duplicate_statuses(db) == 0

    detail = web_client.get(f"/api/expenses/{second_id}", headers=identity.app_headers).json()
    assert detail["duplicate_candidates"] == []
    assert detail["duplicate_status"] == "none"
    assert detail["duplicate_of_id"] is None
    assert detail["row_version"] == version + 1
    assert web_client.get("/api/duplicates", headers=identity.app_headers).json() == []
    assert "没有疑似重复" in web_client.get("/web/duplicates?ledger_id=owner").text
    pending = web_client.get("/api/expenses/pending", headers=identity.app_headers).json()
    assert all(row["duplicate_status"] == "none" for row in pending)
    with SessionLocal() as db:
        assert sidebar_counts(db, "owner") == (2, 0)
        assert data_quality_summary(db, tenant_id="owner").suspected_duplicates == 0
        assert server_settings_snapshot(db, ledger_id="owner", account_name="Owner", ledger_name="Owner",
            device_name="QA", role="owner")["suspected_duplicate_count"] == 0
        for row in db.scalars(select(Expense).where(Expense.tenant_id == "owner")):
            assert {key: getattr(row, key) for key in untouched[row.id]} == untouched[row.id]
