from __future__ import annotations

import json

from api_contract_helpers import confirm_expense_api, expense_updated_at, reject_expense_api
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests._infra.assets import PNG_BYTES


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_family_ledger(client: TestClient, name: str = "家庭拆账本", *, identity) -> str:
    response = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": name})
    assert response.status_code == 201, response.json()
    return str(response.json()["ledger_id"])


def _switch_to(client: TestClient, ledger_id: str, headers: dict[str, str]) -> str:
    response = client.post(f"/api/ledgers/{ledger_id}/switch", headers=headers)
    assert response.status_code == 200, response.json()
    return str(response.json()["session_token"])


def _mint_invitation(
    client: TestClient,
    ledger_id: str,
    owner_token: str,
    *,
    role: str,
) -> str:
    response = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(owner_token),
        json={"role": role},
    )
    assert response.status_code == 201, response.json()
    return str(response.json()["invite_token"])


def _accept_invitation(
    client: TestClient,
    invite_token: str,
    *,
    account_name: str,
) -> str:
    response = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite_token,
            "account_name": account_name,
            "device_name": f"{account_name}-phone",
            "platform": "android",
        },
    )
    assert response.status_code == 200, response.json()
    return str(response.json()["session_token"])


def _make_role_token(
    client: TestClient,
    ledger_id: str,
    owner_token: str,
    *,
    role: str,
    account_name: str,
) -> str:
    invite = _mint_invitation(client, ledger_id, owner_token, role=role)
    return _accept_invitation(client, invite, account_name=account_name)


def _members_by_name(
    client: TestClient, ledger_id: str, token: str
) -> dict[str, dict[str, object]]:
    response = client.get(f"/api/ledgers/{ledger_id}/members", headers=_bearer(token))
    assert response.status_code == 200, response.json()
    return {str(item["account_name"]): item for item in response.json()["members"]}


def _personal_owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return member.id


def _create_manual_expense(
    client: TestClient,
    token: str,
    *,
    amount_cents: int = 10000,
    merchant: str = "家庭晚餐",
) -> int:
    response = client.post(
        "/api/expenses/manual",
        headers=_bearer(token),
        json={
            "amount_cents": amount_cents,
            "merchant": merchant,
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert response.status_code == 200, response.json()
    return int(response.json()["id"])


def _upload_expense(client: TestClient, token: str) -> int:
    response = client.post(
        "/api/app/upload-screenshot",
        headers=_bearer(token),
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "pending"
    return int(response.json()["id"])


def _replace_splits(
    client: TestClient,
    token: str,
    expense_id: int,
    owner_member_id: int,
    member_member_id: int,
    *,
    owner_amount_cents: int = 6000,
    member_amount_cents: int = 3000,
) -> dict[str, object]:
    headers = _bearer(token)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    assert snapshot.status_code == 200, snapshot.json()
    response = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=headers,
        json={
            "expected_updated_at": snapshot.json()["updated_at"],
            "splits": [
                {
                    "member_id": owner_member_id,
                    "amount_cents": owner_amount_cents,
                    "note": "  我出大头  ",
                },
                {
                    "member_id": member_member_id,
                    "amount_cents": member_amount_cents,
                    "note": "一起吃饭",
                },
            ]
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _family_split_fixture(
    client: TestClient, *, identity,
) -> tuple[str, str, str, str, int, int, int]:
    family_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, family_id, identity.app_headers)
    member_token = _make_role_token(
        client,
        family_id,
        owner_token,
        role="member",
        account_name="妈妈",
    )
    viewer_token = _make_role_token(
        client,
        family_id,
        owner_token,
        role="viewer",
        account_name="孩子",
    )
    members = _members_by_name(client, family_id, owner_token)
    owner_member_id = int(members["我"]["member_id"])
    member_member_id = int(members["妈妈"]["member_id"])
    expense_id = _create_manual_expense(client, owner_token)
    return (
        family_id,
        owner_token,
        member_token,
        viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    )


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
    split_audits = [
        item for item in audit.json()["items"] if item["action"] == "expense_splits_replaced"
    ]
    assert split_audits
    latest_audit = split_audits[0]
    assert latest_audit["actor_account_name"] == "妈妈"
    audit_detail = json.loads(latest_audit["detail"])
    assert audit_detail["expense_public_id"] == detail.json()["public_id"]
    assert [item["amount_cents"] for item in audit_detail["before"]] == [6000, 3000]
    assert [item["amount_cents"] for item in audit_detail["after"]] == [5000, 5000]
    assert {
        item["account_public_id"] for item in audit_detail["after"]
    } == {item["account_public_id"] for item in audit_detail["before"]}


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
    client: TestClient, *, identity,
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
            "expected_updated_at": expense_updated_at(
                client, expense_id, headers=_bearer(viewer_token)
            ),
            "splits": [{"member_id": owner_member_id, "amount_cents": 10000}],
        },
    )
    assert viewer_write.status_code == 403
    assert viewer_write.json()["error"] == "permission_denied"


def test_expense_splits_preserve_disabled_member_attribution(
    client: TestClient, *, identity,
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
    disabled_split = next(
        item for item in listed.json()["splits"] if item["member_id"] == member_member_id
    )
    assert disabled_split["account_name"] == "妈妈"
    assert disabled_split["role"] == "member"
    assert disabled_split["disabled_at"] is not None

    replace_with_disabled_member = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=_bearer(owner_token),
        json={
            "expected_updated_at": expense_updated_at(
                client, expense_id, headers=_bearer(owner_token)
            ),
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 5000},
                {"member_id": member_member_id, "amount_cents": 5000},
            ]
        },
    )
    assert replace_with_disabled_member.status_code == 404
    assert replace_with_disabled_member.json()["error"] == "member_not_found"


def test_expense_splits_reject_duplicate_and_cross_ledger_members(
    client: TestClient, *, identity,
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
        headers=_bearer(owner_token),
        json={
            "expected_updated_at": expense_updated_at(
                client, expense_id, headers=_bearer(owner_token)
            ),
            "splits": [
                {"member_id": owner_member_id, "amount_cents": 5000},
                {"member_id": owner_member_id, "amount_cents": 5000},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"] == "invalid_request"

    cross_ledger = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers=_bearer(owner_token),
        json={
            "expected_updated_at": expense_updated_at(
                client, expense_id, headers=_bearer(owner_token)
            ),
            "splits": [
                {"member_id": _personal_owner_member_id(), "amount_cents": 10000}
            ]
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
        headers=_bearer(owner_token),
        json={
            "expected_updated_at": rejected.json()["updated_at"],
            "splits": [{"member_id": owner_member_id, "amount_cents": 10000}],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"] == "expense_not_found"
