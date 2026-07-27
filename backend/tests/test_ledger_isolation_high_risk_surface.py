from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from api_contract_helpers import upload_png
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Expense
from app.routes.web_app import _require_local as _web_require_local
from app.services.time_service import now_utc


@dataclass(frozen=True)
class PendingUploadIds:
    owner: int
    tester: int
    tester_duplicate: int


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


def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
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


def _seed_recurring_expense_pairs(client: TestClient, *, identity: Any) -> None:
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
    # PR #253 R4: 候选扫描窗口为近 6 个月 — 上面的固定日期笔供 stats 断言,
    # 候选判定另补一对相对日期 (固定日期会随时间掉出窗口)。
    recent = (now_utc() - timedelta(days=32)).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    _manual_expense(
        client,
        identity.app_headers,
        merchant="OwnerRecurring",
        amount_cents=1200,
        expense_time=recent,
        category="OwnerOnlyCategory",
    )
    _manual_expense(
        client,
        identity.app_headers,
        merchant="OwnerRecurring",
        amount_cents=1200,
        expense_time=current,
        category="OwnerOnlyCategory",
    )
    _manual_expense(
        client,
        identity.gray_app_headers,
        merchant="TesterRecurring",
        amount_cents=3400,
        expense_time=recent,
        category="TesterOnlyCategory",
    )
    _manual_expense(
        client,
        identity.gray_app_headers,
        merchant="TesterRecurring",
        amount_cents=3400,
        expense_time=current,
        category="TesterOnlyCategory",
    )


def _upload_pending_images(client: TestClient, *, identity: Any) -> PendingUploadIds:
    return PendingUploadIds(
        owner=upload_png(client, identity=identity, headers=identity.upload_headers),
        tester=upload_png(
            client,
            identity=identity,
            headers=identity.gray_upload_headers,
            path=identity.gray_upload_url_path,
        ),
        tester_duplicate=upload_png(
            client,
            identity=identity,
            headers=identity.gray_upload_headers,
            path=identity.gray_upload_url_path,
        ),
    )


def _assert_pending_expenses_are_ledger_scoped(
    client: TestClient,
    *,
    identity: Any,
    upload_ids: PendingUploadIds,
) -> None:
    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert owner_pending.status_code == 200
    assert tester_pending.status_code == 200
    assert [row["id"] for row in owner_pending.json()] == [upload_ids.owner]
    assert {row["id"] for row in tester_pending.json()} == {
        upload_ids.tester,
        upload_ids.tester_duplicate,
    }

    for path in (
        f"/api/expenses/{upload_ids.tester}",
        f"/api/expenses/{upload_ids.tester}/image",
        f"/api/expenses/{upload_ids.tester}/thumbnail",
    ):
        assert client.get(path, headers=identity.app_headers).status_code == 404


def _assert_stats_data_quality_and_duplicates_are_ledger_scoped(
    client: TestClient,
    *,
    identity: Any,
    upload_ids: PendingUploadIds,
) -> None:
    owner_stats = client.get(
        "/api/stats/monthly?month=2026-01&timezone=UTC",
        headers=identity.app_headers,
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
    assert [row["id"] for row in tester_duplicates.json()] == [
        upload_ids.tester_duplicate
    ]


def _assert_exports_are_ledger_scoped(client: TestClient, *, identity: Any) -> None:
    owner_csv = client.get("/api/expenses/export.csv", headers=identity.app_headers)
    tester_csv = client.get("/api/expenses/export.csv", headers=identity.gray_app_headers)
    assert owner_csv.status_code == 200
    assert tester_csv.status_code == 200
    assert "OwnerRecurring" in owner_csv.text
    assert "TesterRecurring" not in owner_csv.text
    assert "TesterRecurring" in tester_csv.text
    assert "OwnerRecurring" not in tester_csv.text


def _assert_rules_are_ledger_scoped(client: TestClient, *, identity: Any) -> None:
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


def _assert_recurring_candidates_are_ledger_scoped(
    client: TestClient,
    *,
    identity: Any,
) -> None:
    owner_candidates = client.get(
        "/api/insights/recurring-candidates?timezone=UTC",
        headers=identity.app_headers,
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
            f"/api/recurring/items/{public_id}",
            headers=identity.gray_app_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/recurring/items/{public_id}/pause",
            headers=identity.gray_app_headers,
            json={"expected_row_version": owner_recurring.json()["row_version"]},
        ).status_code
        == 404
    )


def test_high_risk_api_surfaces_are_ledger_scoped(client: TestClient, *, identity) -> None:
    _seed_recurring_expense_pairs(client, identity=identity)
    upload_ids = _upload_pending_images(client, identity=identity)

    _assert_pending_expenses_are_ledger_scoped(
        client,
        identity=identity,
        upload_ids=upload_ids,
    )
    _assert_stats_data_quality_and_duplicates_are_ledger_scoped(
        client,
        identity=identity,
        upload_ids=upload_ids,
    )
    _assert_exports_are_ledger_scoped(client, identity=identity)
    _assert_rules_are_ledger_scoped(client, identity=identity)
    _assert_recurring_candidates_are_ledger_scoped(client, identity=identity)


def test_protected_image_rejects_path_pointing_at_another_ledger(
    client: TestClient,
    *,
    identity,
) -> None:
    owner_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    tester_id = upload_png(
        client,
        identity=identity,
        headers=identity.gray_upload_headers,
        path=identity.gray_upload_url_path,
    )

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
        f"/api/expenses/{tester_id}/image",
        headers=identity.gray_app_headers,
    )
    assert tester_image.status_code == 200


def _seed_web_ledger_expenses(local_web_client: TestClient, *, identity: Any) -> None:
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


def _assert_web_exports_are_ledger_scoped(local_web_client: TestClient) -> None:
    owner_export = local_web_client.get("/web/export.csv?ledger_id=owner")
    tester_export = local_web_client.get("/web/export.csv?ledger_id=tester_1")
    assert owner_export.status_code == 200
    assert tester_export.status_code == 200
    assert "OwnerWebOnly" in owner_export.text
    assert "TesterWebOnly" not in owner_export.text
    assert "TesterWebOnly" in tester_export.text
    assert "OwnerWebOnly" not in tester_export.text


def _preview_tester_import_batch(local_web_client: TestClient) -> str:
    imported_preview = local_web_client.post(
        "/web/import/preview",
        data={"ledger_id": "tester_1"},
        files={
            "csv_file": (
                "tester.csv",
                (
                    b"amount_cents,merchant,category,expense_time,source\n"
                    b"777,TesterImportedOnly,TesterWebCategory,"
                    b"2026-01-06T00:00:00+00:00,CSV\n"
                    b"bad,TesterImportError,TesterWebCategory,"
                    b"2026-01-07T00:00:00+00:00,CSV\n"
                ),
                "text/csv",
            )
        },
        follow_redirects=False,
    )
    assert imported_preview.status_code == 303
    return imported_preview.headers["location"].split("?", 1)[0]


def _assert_import_batch_is_hidden_from_owner(
    local_web_client: TestClient,
    *,
    batch_path: str,
    identity: Any,
) -> None:
    owner_batch = local_web_client.get(
        f"{batch_path}?ledger_id=owner",
        follow_redirects=False,
    )
    assert owner_batch.status_code == 303
    assert owner_batch.headers["location"].startswith("/web/import?")
    assert "TesterImportedOnly" not in owner_batch.text

    owner_apply = local_web_client.post(
        f"{batch_path}/apply",
        data={"ledger_id": "owner", "batch_size": "500"},
        follow_redirects=False,
    )
    assert owner_apply.status_code == 303
    assert owner_apply.headers["location"].startswith("/web/import?")

    owner_errors = local_web_client.get(
        f"{batch_path}/errors.csv?ledger_id=owner",
        follow_redirects=False,
    )
    assert owner_errors.status_code == 303
    assert owner_errors.headers["location"].startswith("/web/import?")

    owner_pending_before_apply = local_web_client.get(
        "/api/expenses/pending",
        headers=identity.app_headers,
    )
    assert owner_pending_before_apply.status_code == 200
    assert all(
        row["merchant"] != "TesterImportedOnly"
        for row in owner_pending_before_apply.json()
    )


def _apply_tester_import_batch(local_web_client: TestClient, *, batch_path: str) -> None:
    imported = local_web_client.post(
        f"{batch_path}/apply",
        data={"ledger_id": "tester_1", "batch_size": "500"},
        follow_redirects=False,
    )
    assert imported.status_code == 303


def _assert_imported_rows_stay_in_tester_ledger(
    local_web_client: TestClient,
    *,
    identity: Any,
) -> None:
    owner_pending = local_web_client.get(
        "/api/expenses/pending",
        headers=identity.app_headers,
    )
    tester_pending = local_web_client.get(
        "/api/expenses/pending",
        headers=identity.gray_app_headers,
    )
    assert all(row["merchant"] != "TesterImportedOnly" for row in owner_pending.json())
    assert any(row["merchant"] == "TesterImportedOnly" for row in tester_pending.json())


def _assert_web_reports_and_invalid_ledger_scope(local_web_client: TestClient) -> None:
    owner_reports = local_web_client.get("/web/reports?ledger_id=owner&month=2026-01")
    tester_reports = local_web_client.get(
        "/web/reports?ledger_id=tester_1&month=2026-01"
    )
    assert owner_reports.status_code == 200
    assert tester_reports.status_code == 200
    assert "OwnerWebOnly" in owner_reports.text
    assert "TesterWebOnly" not in owner_reports.text
    assert "TesterWebOnly" in tester_reports.text
    assert "OwnerWebOnly" not in tester_reports.text

    invalid_ledger = local_web_client.get("/web?ledger_id=not_a_real_ledger")
    assert invalid_ledger.status_code == 400
    assert invalid_ledger.json()["error"] == "invalid_request"


def test_web_import_export_and_dashboard_keep_selected_ledger_scoped(
    local_web_client: TestClient,
    *,
    identity,
) -> None:
    _seed_web_ledger_expenses(local_web_client, identity=identity)
    _assert_web_exports_are_ledger_scoped(local_web_client)
    batch_path = _preview_tester_import_batch(local_web_client)

    _assert_import_batch_is_hidden_from_owner(
        local_web_client,
        batch_path=batch_path,
        identity=identity,
    )
    _apply_tester_import_batch(local_web_client, batch_path=batch_path)
    _assert_imported_rows_stay_in_tester_ledger(
        local_web_client,
        identity=identity,
    )
    _assert_web_reports_and_invalid_ledger_scope(local_web_client)
