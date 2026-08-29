"""Shared real-HTTP setup for household expense-split tests."""

from __future__ import annotations

from uuid import uuid4

from api_contract_helpers import patch_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests._infra.assets import PNG_BYTES
from tests.pairing_test_support import invitation_accept_payload


def bearer(token: str) -> dict[str, str]:
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
        headers=bearer(owner_token),
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
        json=invitation_accept_payload(
            invite_token,
            account_name=account_name,
            device_name=f"{account_name}-phone",
        ),
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


def _members_by_name(client: TestClient, ledger_id: str, token: str) -> dict[str, dict[str, object]]:
    response = client.get(f"/api/ledgers/{ledger_id}/members", headers=bearer(token))
    assert response.status_code == 200, response.json()
    return {str(item["account_name"]): item for item in response.json()["members"]}


def personal_owner_member_id() -> int:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        return member.id


def upload_expense(client: TestClient, token: str) -> int:
    response = client.post(
        "/api/app/upload-screenshot",
        headers=bearer(token),
        files={"file": ("ticket.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "pending"
    return int(response.json()["id"])


def replace_splits(
    client: TestClient,
    token: str,
    expense_id: int,
    owner_member_id: int,
    member_member_id: int,
    *,
    owner_amount_cents: int = 6000,
    member_amount_cents: int = 3000,
) -> dict[str, object]:
    headers = bearer(token)
    snapshot = client.get(f"/api/expenses/{expense_id}", headers=headers)
    assert snapshot.status_code == 200, snapshot.json()
    response = client.put(
        f"/api/expenses/{expense_id}/splits",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "expected_row_version": snapshot.json()["row_version"],
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
            ],
        },
    )
    assert response.status_code == 200, response.json()
    return response.json()


def family_split_fixture(
    client: TestClient,
    *,
    identity,
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
    expense_id = upload_expense(client, owner_token)
    prepared = patch_expense(
        client,
        expense_id,
        headers=bearer(owner_token),
        fields={
            "amount_cents": 10000,
            "merchant": "家庭晚餐",
            "category": "餐饮",
            "expense_time": "2026-05-04T01:00:00Z",
        },
    )
    assert prepared.status_code == 200, prepared.json()
    return (
        family_id,
        owner_token,
        member_token,
        viewer_token,
        expense_id,
        owner_member_id,
        member_member_id,
    )
