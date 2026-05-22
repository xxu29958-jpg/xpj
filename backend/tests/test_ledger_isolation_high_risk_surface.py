from __future__ import annotations

import pytest
from api_contract_helpers import upload_png
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local


def _manual_expense(
    client: TestClient,
    headers: dict[str, str],
    *,
    merchant: str,
    amount_cents: int,
    expense_time: str,
    category: str,
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=headers,
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": category,
            "expense_time": expense_time,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def _candidate_payload(item: dict) -> dict:
    return {
        "merchant": item["merchant"],
        "amount_cents": item["amount_cents"],
        "occurrence_count": item["occurrence_count"],
        "last_seen_at": item["last_seen_at"],
        "confidence": item["confidence"],
        "frequency": "monthly",
    }


@pytest.fixture()
def local_web_client(client: TestClient) -> TestClient:
    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


def test_high_risk_api_surfaces_are_ledger_scoped(client: TestClient, *, identity) -> None:
    _manual_expense(
        client,
        identity.app_headers,
        merchant="OwnerRecurring",
        amount_cents=1200,
        expense_time="2026-01-05T00:00:00Z",
        category="OwnerOnlyCategory",
    )
    _manual_expense(
        client,
        identity.app_headers,
        merchant="OwnerRecurring",
        amount_cents=1200,
        expense_time="2026-02-05T00:00:00Z",
        category="OwnerOnlyCategory",
    )
    _manual_expense(
        client,
        identity.gray_app_headers,
        merchant="TesterRecurring",
        amount_cents=3400,
        expense_time="2026-01-05T00:00:00Z",
        category="TesterOnlyCategory",
    )
    _manual_expense(
        client,
        identity.gray_app_headers,
        merchant="TesterRecurring",
        amount_cents=3400,
        expense_time="2026-02-05T00:00:00Z",
        category="TesterOnlyCategory",
    )

    owner_pending_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    tester_pending_id = upload_png(client, identity=identity, headers=identity.gray_upload_headers, path=identity.gray_upload_url_path)
    tester_duplicate_id = upload_png(client, identity=identity, headers=identity.gray_upload_headers, path=identity.gray_upload_url_path)

    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert owner_pending.status_code == 200
    assert tester_pending.status_code == 200
    assert [row["id"] for row in owner_pending.json()] == [owner_pending_id]
    assert {row["id"] for row in tester_pending.json()} == {
        tester_pending_id,
        tester_duplicate_id,
    }

    for path in (
        f"/api/expenses/{tester_pending_id}",
        f"/api/expenses/{tester_pending_id}/image",
        f"/api/expenses/{tester_pending_id}/thumbnail",
    ):
        assert client.get(path, headers=identity.app_headers).status_code == 404

    owner_stats = client.get(
        "/api/stats/monthly?month=2026-01&timezone=UTC", headers=identity.app_headers
    )
    tester_stats = client.get(
        "/api/stats/monthly?month=2026-01&timezone=UTC",
        headers=identity.gray_app_headers,
    )
    assert owner_stats.status_code == 200
    assert tester_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1200
    assert tester_stats.json()["total_amount_cents"] == 3400

    owner_dq = client.get("/api/insights/data-quality", headers=identity.app_headers)
    tester_dq = client.get("/api/insights/data-quality", headers=identity.gray_app_headers)
    assert owner_dq.status_code == 200
    assert tester_dq.status_code == 200
    assert owner_dq.json()["pending_total"] == 1
    assert tester_dq.json()["pending_total"] == 2
    assert owner_dq.json()["suspected_duplicates"] == 0
    assert tester_dq.json()["suspected_duplicates"] == 1

    owner_duplicates = client.get("/api/duplicates", headers=identity.app_headers)
    tester_duplicates = client.get("/api/duplicates", headers=identity.gray_app_headers)
    assert owner_duplicates.status_code == 200
    assert tester_duplicates.status_code == 200
    assert owner_duplicates.json() == []
    assert [row["id"] for row in tester_duplicates.json()] == [tester_duplicate_id]

    owner_csv = client.get("/api/expenses/export.csv", headers=identity.app_headers)
    tester_csv = client.get("/api/expenses/export.csv", headers=identity.gray_app_headers)
    assert owner_csv.status_code == 200
    assert tester_csv.status_code == 200
    assert "OwnerRecurring" in owner_csv.text
    assert "TesterRecurring" not in owner_csv.text
    assert "TesterRecurring" in tester_csv.text
    assert "OwnerRecurring" not in tester_csv.text

    owner_rule = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "owner-rule-token",
            "category": "OwnerOnlyCategory",
            "enabled": True,
            "priority": 1,
        },
    )
    assert owner_rule.status_code == 200
    tester_rules = client.get("/api/rules/categories", headers=identity.gray_app_headers)
    assert tester_rules.status_code == 200
    assert all(row["keyword"] != "owner-rule-token" for row in tester_rules.json())

    owner_candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC", headers=identity.app_headers
    )
    tester_candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC",
        headers=identity.gray_app_headers,
    )
    assert owner_candidates.status_code == 200
    assert tester_candidates.status_code == 200
    assert [row["merchant"] for row in owner_candidates.json()["items"]] == [
        "OwnerRecurring"
    ]
    assert [row["merchant"] for row in tester_candidates.json()["items"]] == [
        "TesterRecurring"
    ]

    owner_recurring = client.post(
        "/api/recurring/from-candidate?timezone=UTC",
        headers=identity.app_headers,
        json=_candidate_payload(owner_candidates.json()["items"][0]),
    )
    assert owner_recurring.status_code == 200, owner_recurring.text
    public_id = owner_recurring.json()["public_id"]
    assert (
        client.get(
            f"/api/recurring/items/{public_id}", headers=identity.gray_app_headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/recurring/items/{public_id}/pause", headers=identity.gray_app_headers
        ).status_code
        == 404
    )


def test_protected_image_rejects_path_pointing_at_another_ledger(
    client: TestClient, *, identity,
) -> None:
    owner_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    tester_id = upload_png(client, identity=identity, headers=identity.gray_upload_headers, path=identity.gray_upload_url_path)

    with SessionLocal() as db:
        owner = db.get(Expense, owner_id)
        tester = db.get(Expense, tester_id)
        assert owner is not None
        assert tester is not None
        assert tester.image_path is not None
        owner.image_path = tester.image_path
        db.commit()

    owner_image = client.get(f"/api/expenses/{owner_id}/image", headers=identity.app_headers)
    assert owner_image.status_code == 404
    assert owner_image.json()["error"] == "image_not_found"

    tester_image = client.get(
        f"/api/expenses/{tester_id}/image", headers=identity.gray_app_headers
    )
    assert tester_image.status_code == 200


def test_web_import_export_and_dashboard_keep_selected_ledger_scoped(
    local_web_client: TestClient, *, identity,
) -> None:
    _manual_expense(
        local_web_client,
        identity.app_headers,
        merchant="OwnerWebOnly",
        amount_cents=1200,
        expense_time="2026-01-05T00:00:00Z",
        category="OwnerWebCategory",
    )
    _manual_expense(
        local_web_client,
        identity.gray_app_headers,
        merchant="TesterWebOnly",
        amount_cents=3400,
        expense_time="2026-01-05T00:00:00Z",
        category="TesterWebCategory",
    )

    owner_export = local_web_client.get("/web/export.csv?ledger_id=owner")
    tester_export = local_web_client.get("/web/export.csv?ledger_id=tester_1")
    assert owner_export.status_code == 200
    assert tester_export.status_code == 200
    assert "OwnerWebOnly" in owner_export.text
    assert "TesterWebOnly" not in owner_export.text
    assert "TesterWebOnly" in tester_export.text
    assert "OwnerWebOnly" not in tester_export.text

    imported_preview = local_web_client.post(
        "/web/import/preview",
        data={"ledger_id": "tester_1"},
        files={
            "csv_file": (
                "tester.csv",
                (
                    b"amount_cents,merchant,category,expense_time,source\n"
                    b"777,TesterImportedOnly,TesterWebCategory,2026-01-06T00:00:00+00:00,CSV\n"
                    b"bad,TesterImportError,TesterWebCategory,2026-01-07T00:00:00+00:00,CSV\n"
                ),
                "text/csv",
            )
        },
        follow_redirects=False,
    )
    assert imported_preview.status_code == 303
    location = imported_preview.headers["location"]
    batch_path = location.split("?", 1)[0]

    owner_batch = local_web_client.get(f"{batch_path}?ledger_id=owner")
    assert owner_batch.status_code == 404
    assert owner_batch.json()["error"] == "import_batch_not_found"

    owner_apply = local_web_client.post(
        f"{batch_path}/apply",
        data={"ledger_id": "owner", "batch_size": "500"},
        follow_redirects=False,
    )
    assert owner_apply.status_code == 404
    assert owner_apply.json()["error"] == "import_batch_not_found"

    owner_errors = local_web_client.get(f"{batch_path}/errors.csv?ledger_id=owner")
    assert owner_errors.status_code == 404
    assert owner_errors.json()["error"] == "import_batch_not_found"

    owner_pending_before_tester_apply = local_web_client.get(
        "/api/expenses/pending", headers=identity.app_headers
    )
    assert owner_pending_before_tester_apply.status_code == 200
    assert all(
        row["merchant"] != "TesterImportedOnly"
        for row in owner_pending_before_tester_apply.json()
    )

    imported = local_web_client.post(
        f"{batch_path}/apply",
        data={"ledger_id": "tester_1", "batch_size": "500"},
        follow_redirects=False,
    )
    assert imported.status_code == 303

    owner_pending = local_web_client.get("/api/expenses/pending", headers=identity.app_headers)
    tester_pending = local_web_client.get(
        "/api/expenses/pending", headers=identity.gray_app_headers
    )
    assert all(row["merchant"] != "TesterImportedOnly" for row in owner_pending.json())
    assert any(row["merchant"] == "TesterImportedOnly" for row in tester_pending.json())

    owner_stats = local_web_client.get("/web/stats?ledger_id=owner&month=2026-01")
    tester_stats = local_web_client.get("/web/stats?ledger_id=tester_1&month=2026-01")
    assert owner_stats.status_code == 200
    assert tester_stats.status_code == 200
    assert "OwnerWebOnly" in owner_stats.text
    assert "TesterWebOnly" not in owner_stats.text
    assert "TesterWebOnly" in tester_stats.text
    assert "OwnerWebOnly" not in tester_stats.text

    invalid_ledger = local_web_client.get("/web?ledger_id=not_a_real_ledger")
    assert invalid_ledger.status_code == 400
    assert invalid_ledger.json()["error"] == "invalid_request"
