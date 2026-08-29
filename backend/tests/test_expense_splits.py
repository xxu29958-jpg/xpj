from __future__ import annotations

import json
from uuid import uuid4

from api_contract_helpers import (
    confirm_expense_api,
    expense_row_version,
    reject_expense_api,
)
from fastapi.testclient import TestClient

from tests.expense_split_test_support import bearer as _bearer
from tests.expense_split_test_support import family_split_fixture as _family_split_fixture
from tests.expense_split_test_support import personal_owner_member_id as _personal_owner_member_id
from tests.expense_split_test_support import replace_splits as _replace_splits
from tests.expense_split_test_support import upload_expense as _upload_expense


def test_expense_splits_replace_read_and_audit(client: TestClient, *, identity) -> None:
    (
        family_id,
        owner_token,
        member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = _family_split_fixture(client, identity=identity)

    replaced = _replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
    )

    assert replaced["expense_id"] == expense_id
    assert replaced["parent_amount_cents"] == 10000
    assert replaced["splits_total_amount_cents"] == 9000
    assert replaced["mismatch_cents"] == 1000
    assert [item["position"] for item in replaced["splits"]] == [0, 1]
    assert [item["account_name"] for item in replaced["splits"]] == ["我", "妈妈"]
    assert [item["role"] for item in replaced["splits"]] == ["owner", "member"]
    assert replaced["splits"][0]["note"] == "我出大头"

    member_replaced = _replace_splits(
        client,
        member_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=5000,
        member_amount_cents=5000,
    )
    assert member_replaced["splits_total_amount_cents"] == 10000
    assert member_replaced["mismatch_cents"] == 0

    listed = client.get(f"/api/expenses/{expense_id}/splits", headers=_bearer(owner_token))
    assert listed.status_code == 200, listed.json()
    assert listed.json() == member_replaced

    detail = client.get(f"/api/expenses/{expense_id}", headers=_bearer(owner_token))
    assert detail.status_code == 200, detail.json()
    assert "splits" not in detail.json()

    audit = client.get(f"/api/ledgers/{family_id}/audit", headers=_bearer(owner_token))
    assert audit.status_code == 200, audit.json()
    split_audits = [item for item in audit.json()["items"] if item["action"] == "expense_splits_replaced"]
    assert split_audits
    latest_audit = split_audits[0]
    assert latest_audit["actor_account_name"] == "妈妈"
    audit_detail = json.loads(latest_audit["detail"])
    assert audit_detail["expense_public_id"] == detail.json()["public_id"]
    assert [item["amount_cents"] for item in audit_detail["before"]] == [6000, 3000]
    assert [item["amount_cents"] for item in audit_detail["after"]] == [5000, 5000]
    assert {item["account_public_id"] for item in audit_detail["after"]} == {
        item["account_public_id"] for item in audit_detail["before"]
    }


def test_expense_splits_replace_response_carries_bumped_parent_row_version(
    client: TestClient,
    *,
    identity,
) -> None:
    """ADR-0041 self-describing contract: PUT /splits returns the *parent*
    expense's row_version, advanced past the value the client sent — so a
    chained client can reuse it without a second GET on the expense."""
    (_f, owner_token, _m, _v, expense_id, owner_member_id, member_member_id) = _family_split_fixture(
        client, identity=identity
    )
    before = expense_row_version(client, expense_id, headers=_bearer(owner_token))

    replaced = _replace_splits(client, owner_token, expense_id, owner_member_id, member_member_id)
    assert replaced["row_version"] == before + 1
    # The bumped token matches the parent's current state, and GET /splits
    # mirrors it (no extra bump).
    detail = client.get(f"/api/expenses/{expense_id}", headers=_bearer(owner_token))
    assert detail.json()["row_version"] == replaced["row_version"]
    listed = client.get(f"/api/expenses/{expense_id}/splits", headers=_bearer(owner_token))
    assert listed.json()["row_version"] == replaced["row_version"]


def test_expense_splits_do_not_change_stats_or_export(client: TestClient, *, identity) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = _family_split_fixture(client, identity=identity)
    replaced = _replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
        owner_amount_cents=4321,
        member_amount_cents=5678,
    )
    assert replaced["splits_total_amount_cents"] == 9999

    confirmed = confirm_expense_api(client, expense_id, headers=_bearer(owner_token))
    assert confirmed.status_code == 200, confirmed.json()

    stats = client.get("/api/stats/monthly?month=2026-05", headers=_bearer(owner_token))
    assert stats.status_code == 200, stats.json()
    assert stats.json()["total_amount_cents"] == 10000

    exported = client.get(
        "/api/expenses/export.csv?month=2026-05&category=餐饮",
        headers=_bearer(owner_token),
    )
    assert exported.status_code == 200, exported.text
    assert "家庭晚餐" in exported.text
    assert ",10000," in exported.text
    assert ",9999," not in exported.text


def test_expense_splits_are_tenant_isolated_and_viewer_can_only_read(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = _family_split_fixture(client, identity=identity)
    _replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
    )

    gray_read = client.get(f"/api/expenses/{expense_id}/splits", headers=identity.gray_app_headers)
    assert gray_read.status_code == 404
    assert gray_read.json()["error"] == "expense_not_found"

    viewer_read = client.get(f"/api/expenses/{expense_id}/splits", headers=_bearer(viewer_token))
    assert viewer_read.status_code == 200, viewer_read.json()
    assert [item["account_name"] for item in viewer_read.json()["splits"]] == ["我", "妈妈"]

    viewer_write = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=_bearer(viewer_token),
        json={
            "expected_row_version": expense_row_version(client, expense_id, headers=_bearer(viewer_token)),
            "splits": [{"member_id": owner_member_id, "amount_cents": 10000}],
        },
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"


def test_expense_splits_preserve_disabled_member_attribution(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    ) = _family_split_fixture(client, identity=identity)
    _replace_splits(
        client,
        owner_token,
        expense_id,
        owner_member_id,
        member_member_id,
    )

    disabled = client.post(
        f"/api/ledgers/{family_id}/members/{member_member_id}/disable",
        headers=_bearer(owner_token),
    )
    assert disabled.status_code == 200, disabled.json()
    assert disabled.json()["disabled_at"] is not None

    listed = client.get(f"/api/expenses/{expense_id}/splits", headers=_bearer(owner_token))
    assert listed.status_code == 200, listed.json()
    disabled_split = next(item for item in listed.json()["splits"] if item["member_id"] == member_member_id)
    assert disabled_split["account_name"] == "妈妈"
    assert disabled_split["role"] == "member"
    assert disabled_split["disabled_at"] is not None

    replace_with_disabled_member = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**_bearer(owner_token), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": expense_row_version(client, expense_id, headers=_bearer(owner_token)),
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 5000},
                {"member_id": member_member_id, "amount_cents": 5000},
            ],
        },
    )
    assert replace_with_disabled_member.status_code == 404
    assert replace_with_disabled_member.json()["error"] == "member_not_found"


def test_expense_splits_reject_duplicate_and_cross_ledger_members(
    client: TestClient,
    *,
    identity,
) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        expense_id,
        owner_member_id,
        _member_member_id,
    ) = _family_split_fixture(client, identity=identity)

    duplicate = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**_bearer(owner_token), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": expense_row_version(client, expense_id, headers=_bearer(owner_token)),
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 5000},
                {"member_id": owner_member_id, "amount_cents": 5000},
            ],
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"] == "invalid_request"

    cross_ledger = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**_bearer(owner_token), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": expense_row_version(client, expense_id, headers=_bearer(owner_token)),
            "splits": [{"member_id": _personal_owner_member_id(), "amount_cents": 10000}],
        },
    )
    assert cross_ledger.status_code == 404
    assert cross_ledger.json()["error"] == "member_not_found"


def test_rejected_expense_splits_cannot_be_replaced(client: TestClient, *, identity) -> None:
    (
        _family_id,
        owner_token,
        _member_token,
        _viewer_token,
        _expense_id,
        owner_member_id,
        _member_member_id,
    ) = _family_split_fixture(client, identity=identity)
    expense_id = _upload_expense(client, owner_token)
    rejected = reject_expense_api(client, expense_id, headers=_bearer(owner_token))
    assert rejected.status_code == 200, rejected.json()

    response = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**_bearer(owner_token), "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": rejected.json()["row_version"],
            "splits": [{"member_id": owner_member_id, "amount_cents": 10000}],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"] == "expense_not_found"


def test_put_expense_splits_without_auth_returns_401(client: TestClient) -> None:
    # codex P2 #9: route-test-matrix 守护要求 mutating route 都有 401 拒绝测试。
    # PUT /api/expenses/{expense_id}/splits 用 Depends(get_current_writer_context),
    # dependency 先 resolve,无 token 在 body parse 前直接拒(expense_id=1 不会真去查 DB)。
    response = client.put(
        "/api/expenses/1/splits",
        json={"expected_row_version": "2026-01-01T00:00:00Z", "splits": []},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
