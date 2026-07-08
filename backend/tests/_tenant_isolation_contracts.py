from __future__ import annotations

from api_contract_helpers import confirm_expense_api, patch_expense, reject_expense_api, upload_png
from fastapi.testclient import TestClient

from tests._infra.env import TEST_UPLOAD_RELATIVE


def _upload_owner_and_tester_receipts(client: TestClient, *, identity) -> tuple[int, int]:
    owner_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    tester_id = upload_png(
        client,
        identity=identity,
        headers=identity.gray_upload_headers,
        path=identity.gray_upload_url_path,
    )
    return owner_id, tester_id


def _assert_pending_receipts_are_ledger_scoped(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert owner_pending.status_code == 200
    assert tester_pending.status_code == 200
    assert [item["id"] for item in owner_pending.json()] == [owner_id]
    assert [item["id"] for item in tester_pending.json()] == [tester_id]


def _assert_tester_cannot_read_owner_receipt(
    client: TestClient,
    *,
    identity,
    owner_id: int,
) -> None:
    for path in [
        f"/api/expenses/{owner_id}",
        f"/api/expenses/{owner_id}/image",
        f"/api/expenses/{owner_id}/thumbnail",
    ]:
        assert client.get(path, headers=identity.gray_app_headers).status_code == 404


def _confirm_owner_may_expense(client: TestClient, *, identity, owner_id: int) -> None:
    owner_patch = patch_expense(
        client,
        owner_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 1000,
            "merchant": "owner商家",
            "category": "生活",
            "expense_time": "2026-05-04T00:00:00Z",
        },
    )
    assert owner_patch.status_code == 200
    assert confirm_expense_api(client, owner_id, headers=identity.app_headers).status_code == 200


def _assert_owner_expense_is_hidden_from_tester_reports(client: TestClient, *, identity) -> None:
    tester_stats = client.get(
        "/api/stats/monthly?month=2026-05", headers=identity.gray_app_headers
    )
    assert tester_stats.status_code == 200
    assert tester_stats.json()["total_amount_cents"] == 0

    owner_stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    assert owner_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1000

    tester_csv = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=identity.gray_app_headers
    )
    assert tester_csv.status_code == 200
    assert "owner商家" not in tester_csv.text


def _assert_category_rule_stays_in_tester_ledger(client: TestClient, *, identity) -> None:
    rule = client.post(
        "/api/rules/categories",
        headers=identity.gray_app_headers,
        json={
            "keyword": "只属于tester",
            "category": "购物",
            "enabled": True,
            "priority": 1,
        },
    )
    assert rule.status_code == 200
    owner_rules = client.get("/api/rules/categories", headers=identity.app_headers).json()
    tester_rules = client.get(
        "/api/rules/categories", headers=identity.gray_app_headers
    ).json()
    assert all(item["keyword"] != "只属于tester" for item in owner_rules)
    assert any(item["keyword"] == "只属于tester" for item in tester_rules)


def _assert_pending_duplicate_detection_stays_in_current_ledger(
    client: TestClient,
    *,
    identity,
    tester_id: int,
) -> None:
    second_owner_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    owner_duplicates = client.get("/api/duplicates", headers=identity.app_headers).json()
    tester_duplicates = client.get("/api/duplicates", headers=identity.gray_app_headers).json()
    assert any(item["id"] == second_owner_id for item in owner_duplicates)
    assert all(item["id"] != second_owner_id for item in tester_duplicates)

    same_hash_tester_id = upload_png(
        client,
        identity=identity,
        headers=identity.gray_upload_headers,
        path=identity.gray_upload_url_path,
    )
    same_hash_tester_pending = client.get(
        "/api/expenses/pending", headers=identity.gray_app_headers
    ).json()
    tester_match = next(
        item for item in same_hash_tester_pending if item["id"] == same_hash_tester_id
    )
    assert tester_match["duplicate_status"] == "suspected"
    assert tester_match["duplicate_of_id"] == tester_id
    assert tester_match["duplicate_of_id"] != second_owner_id


def _assert_upload_paths_are_ledger_scoped(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_detail = client.get(f"/api/expenses/{owner_id}", headers=identity.app_headers).json()
    tester_detail = client.get(
        f"/api/expenses/{tester_id}", headers=identity.gray_app_headers
    ).json()
    assert owner_detail["image_path"].startswith(f"{TEST_UPLOAD_RELATIVE}/owner/")
    assert tester_detail["image_path"].startswith(f"{TEST_UPLOAD_RELATIVE}/tester_1/")
    if owner_detail["thumbnail_path"]:
        assert owner_detail["thumbnail_path"].startswith(f"{TEST_UPLOAD_RELATIVE}/owner/")
    if tester_detail["thumbnail_path"]:
        assert tester_detail["thumbnail_path"].startswith(f"{TEST_UPLOAD_RELATIVE}/tester_1/")


def _assert_cross_ledger_expense_mutations_are_hidden(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    cross_mutations = [
        patch_expense(
            client,
            tester_id,
            headers=identity.app_headers,
            fields={"amount_cents": 1, "merchant": "owner不该改tester"},
        ),
        confirm_expense_api(client, tester_id, headers=identity.app_headers),
        reject_expense_api(client, tester_id, headers=identity.app_headers),
        patch_expense(
            client,
            owner_id,
            headers=identity.gray_app_headers,
            fields={"amount_cents": 1, "merchant": "tester不该改owner"},
        ),
        confirm_expense_api(client, owner_id, headers=identity.gray_app_headers),
        reject_expense_api(client, owner_id, headers=identity.gray_app_headers),
    ]
    for response in cross_mutations:
        assert response.status_code == 404
        assert response.json()["error"] == "expense_not_found"


def _assert_cross_ledger_expense_reads_are_hidden(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    _assert_tester_cannot_read_owner_receipt(client, identity=identity, owner_id=owner_id)
    for path in [
        f"/api/expenses/{tester_id}",
        f"/api/expenses/{tester_id}/image",
        f"/api/expenses/{tester_id}/thumbnail",
    ]:
        assert client.get(path, headers=identity.app_headers).status_code == 404


def _confirm_owner_and_tester_isolation_expenses(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_patch = patch_expense(
        client,
        owner_id,
        headers=identity.app_headers,
        fields={
            "amount_cents": 1111,
            "merchant": "owner隔离商家",
            "category": "Owner自定义类",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    tester_patch = patch_expense(
        client,
        tester_id,
        headers=identity.gray_app_headers,
        fields={
            "amount_cents": 2222,
            "merchant": "tester隔离商家",
            "category": "Tester自定义类",
            "expense_time": "2026-05-04T02:00:00Z",
        },
    )
    assert owner_patch.status_code == 200
    assert tester_patch.status_code == 200
    assert confirm_expense_api(client, owner_id, headers=identity.app_headers).status_code == 200
    assert (
        confirm_expense_api(client, tester_id, headers=identity.gray_app_headers).status_code
        == 200
    )


def _assert_confirmed_expense_lists_are_ledger_scoped(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.app_headers
    )
    tester_confirmed = client.get(
        "/api/expenses/confirmed?month=2026-05", headers=identity.gray_app_headers
    )
    assert owner_confirmed.status_code == 200
    assert tester_confirmed.status_code == 200
    assert [item["id"] for item in owner_confirmed.json()["items"]] == [owner_id]
    assert [item["id"] for item in tester_confirmed.json()["items"]] == [tester_id]


def _assert_monthly_stats_are_ledger_scoped(client: TestClient, *, identity) -> None:
    owner_stats = client.get("/api/stats/monthly?month=2026-05", headers=identity.app_headers)
    tester_stats = client.get(
        "/api/stats/monthly?month=2026-05", headers=identity.gray_app_headers
    )
    assert owner_stats.status_code == 200
    assert tester_stats.status_code == 200
    assert owner_stats.json()["total_amount_cents"] == 1111
    assert tester_stats.json()["total_amount_cents"] == 2222
    assert owner_stats.json()["count"] == 1
    assert tester_stats.json()["count"] == 1


def _assert_lifestyle_stats_are_ledger_scoped(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=identity.app_headers
    )
    tester_lifestyle = client.get(
        "/api/stats/lifestyle?month=2026-05", headers=identity.gray_app_headers
    )
    assert owner_lifestyle.status_code == 200
    assert tester_lifestyle.status_code == 200
    assert owner_lifestyle.json()["max_expense"]["id"] == owner_id
    assert tester_lifestyle.json()["max_expense"]["id"] == tester_id
    assert owner_lifestyle.json()["max_expense"]["merchant"] == "owner隔离商家"
    assert tester_lifestyle.json()["max_expense"]["merchant"] == "tester隔离商家"


def _assert_exports_are_ledger_scoped(client: TestClient, *, identity) -> None:
    owner_export = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=identity.app_headers
    )
    tester_export = client.get(
        "/api/expenses/export.csv?month=2026-05", headers=identity.gray_app_headers
    )
    assert owner_export.status_code == 200
    assert tester_export.status_code == 200
    assert "owner隔离商家" in owner_export.text
    assert "tester隔离商家" not in owner_export.text
    assert "tester隔离商家" in tester_export.text
    assert "owner隔离商家" not in tester_export.text


def _assert_categories_are_ledger_scoped(client: TestClient, *, identity) -> None:
    owner_categories = client.get(
        "/api/expenses/categories", headers=identity.app_headers
    ).json()["items"]
    tester_categories = client.get(
        "/api/expenses/categories", headers=identity.gray_app_headers
    ).json()["items"]
    assert "Owner自定义类" in owner_categories
    assert "Tester自定义类" not in owner_categories
    assert "Tester自定义类" in tester_categories
    assert "Owner自定义类" not in tester_categories


def _assert_category_rules_are_ledger_scoped(client: TestClient, *, identity) -> None:
    owner_rule = client.post(
        "/api/rules/categories",
        headers=identity.app_headers,
        json={
            "keyword": "owner规则",
            "category": "Owner自定义类",
            "enabled": True,
            "priority": 1,
        },
    )
    tester_rule = client.post(
        "/api/rules/categories",
        headers=identity.gray_app_headers,
        json={
            "keyword": "tester规则",
            "category": "Tester自定义类",
            "enabled": True,
            "priority": 1,
        },
    )
    assert owner_rule.status_code == 200
    assert tester_rule.status_code == 200
    owner_rules = client.get("/api/rules/categories", headers=identity.app_headers).json()
    tester_rules = client.get(
        "/api/rules/categories", headers=identity.gray_app_headers
    ).json()
    assert any(item["keyword"] == "owner规则" for item in owner_rules)
    assert all(item["keyword"] != "tester规则" for item in owner_rules)
    assert any(item["keyword"] == "tester规则" for item in tester_rules)
    assert all(item["keyword"] != "owner规则" for item in tester_rules)


def _assert_server_settings_are_ledger_scoped(client: TestClient, *, identity) -> None:
    owner_settings = client.get("/api/settings/server", headers=identity.app_headers).json()
    tester_settings = client.get(
        "/api/settings/server", headers=identity.gray_app_headers
    ).json()
    assert owner_settings["ledger_name"] == "我的小票夹"
    assert tester_settings["ledger_name"] == "灰度用户1"
    assert owner_settings["confirmed_count"] == 1
    assert tester_settings["confirmed_count"] == 1
    assert owner_settings["pending_count"] == 0
    assert tester_settings["pending_count"] == 0
    assert owner_settings["rejected_count"] == 0
    assert tester_settings["rejected_count"] == 0
    assert owner_settings["upload_storage_bytes"] > 0
    assert tester_settings["upload_storage_bytes"] > 0
    assert owner_settings["latest_upload_at"].endswith("Z")
    assert tester_settings["latest_upload_at"].endswith("Z")


def _assert_confirmed_duplicate_detection_is_ledger_scoped(
    client: TestClient,
    *,
    identity,
    owner_id: int,
    tester_id: int,
) -> None:
    owner_duplicate_id = upload_png(client, identity=identity, headers=identity.upload_headers)
    tester_duplicate_id = upload_png(
        client,
        identity=identity,
        headers=identity.gray_upload_headers,
        path=identity.gray_upload_url_path,
    )
    owner_duplicates = client.get("/api/duplicates", headers=identity.app_headers).json()
    tester_duplicates = client.get("/api/duplicates", headers=identity.gray_app_headers).json()
    assert any(
        item["id"] == owner_duplicate_id and item["duplicate_of_id"] == owner_id
        for item in owner_duplicates
    )
    assert all(item["id"] != tester_duplicate_id for item in owner_duplicates)
    assert any(
        item["id"] == tester_duplicate_id and item["duplicate_of_id"] == tester_id
        for item in tester_duplicates
    )
    assert all(item["id"] != owner_duplicate_id for item in tester_duplicates)
