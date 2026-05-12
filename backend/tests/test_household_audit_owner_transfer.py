from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Ledger, LedgerAuditLog, LedgerMember
from conftest import admin_headers, app_headers


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_family_ledger(client: TestClient, name: str = "家庭账本") -> str:
    resp = client.post("/api/ledgers", headers=admin_headers(), json={"name": name})
    assert resp.status_code == 201, resp.json()
    return resp.json()["ledger_id"]


def _switch_to(client: TestClient, ledger_id: str, headers: dict[str, str]) -> str:
    resp = client.post(f"/api/ledgers/{ledger_id}/switch", headers=headers)
    assert resp.status_code == 200, resp.json()
    return resp.json()["session_token"]


def _mint_invitation(client: TestClient, ledger_id: str, owner_token: str, role: str = "member") -> str:
    resp = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(owner_token),
        json={"role": role, "note": "家庭成员"},
    )
    assert resp.status_code == 201, resp.json()
    return str(resp.json()["invite_token"])


def _accept_invitation(
    client: TestClient,
    invite_token: str,
    *,
    account_name: str = "家人",
    device_name: str = "Family-Phone",
) -> str:
    resp = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite_token,
            "account_name": account_name,
            "device_name": device_name,
            "platform": "android",
        },
    )
    assert resp.status_code == 200, resp.json()
    return str(resp.json()["session_token"])


def _member_id_for_role(client: TestClient, ledger_id: str, token: str, role: str) -> int:
    resp = client.get(f"/api/ledgers/{ledger_id}/members", headers=_bearer(token))
    assert resp.status_code == 200, resp.json()
    return int(next(row for row in resp.json()["members"] if row["role"] == role)["member_id"])


def _active_owner_count(ledger_id: str) -> int:
    with SessionLocal() as db:
        return int(
            db.scalar(
                select(func.count())
                .select_from(LedgerMember)
                .where(LedgerMember.ledger_id == ledger_id)
                .where(LedgerMember.role == "owner")
                .where(LedgerMember.disabled_at.is_(None))
            )
            or 0
        )


def test_family_member_audit_records_sensitive_safe_actions(client: TestClient) -> None:
    ledger_id = _create_family_ledger(client)
    owner_token = _switch_to(client, ledger_id, app_headers())

    invite_token = _mint_invitation(client, ledger_id, owner_token)
    member_token = _accept_invitation(client, invite_token, account_name="妈妈")
    member_id = _member_id_for_role(client, ledger_id, owner_token, "member")

    role_change = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/role",
        headers=_bearer(owner_token),
        json={"role": "viewer"},
    )
    assert role_change.status_code == 200, role_change.json()

    disable = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/disable",
        headers=_bearer(owner_token),
    )
    assert disable.status_code == 200, disable.json()

    revoke_token = _mint_invitation(client, ledger_id, owner_token, role="viewer")
    invitations = client.get(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(owner_token),
    ).json()["invitations"]
    revoke_public_id = next(row for row in invitations if row["used_at"] is None)["public_id"]
    revoke = client.post(
        f"/api/ledgers/{ledger_id}/invitations/{revoke_public_id}/revoke",
        headers=_bearer(owner_token),
    )
    assert revoke.status_code == 200, revoke.json()

    audit = client.get(f"/api/ledgers/{ledger_id}/audit", headers=_bearer(owner_token))
    assert audit.status_code == 200, audit.json()
    payload = audit.json()
    actions = [row["action"] for row in payload["items"]]
    assert "invitation_created" in actions
    assert "invitation_accepted" in actions
    assert "member_role_changed" in actions
    assert "member_disabled" in actions
    assert "invitation_revoked" in actions

    serialized = json.dumps(payload, ensure_ascii=False)
    assert invite_token not in serialized
    assert revoke_token not in serialized
    assert member_token not in serialized
    assert "/u/" not in serialized
    assert "E:\\projects" not in serialized

    with SessionLocal() as db:
        stored = list(db.scalars(select(LedgerAuditLog).where(LedgerAuditLog.ledger_id == ledger_id)))
    assert stored
    assert all(row.result == "success" for row in stored)


def test_owner_transfer_keeps_single_owner_and_demotes_previous_owner(client: TestClient) -> None:
    ledger_id = _create_family_ledger(client)
    owner_token = _switch_to(client, ledger_id, app_headers())
    invite_token = _mint_invitation(client, ledger_id, owner_token)
    member_token = _accept_invitation(client, invite_token, account_name="爸爸")
    member_id = _member_id_for_role(client, ledger_id, owner_token, "member")

    transfer = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
        headers=_bearer(owner_token),
    )
    assert transfer.status_code == 200, transfer.json()
    body = transfer.json()
    assert body["previous_owner"]["role"] == "member"
    assert body["new_owner"]["role"] == "owner"
    assert _active_owner_count(ledger_id) == 1

    old_check = client.get("/api/auth/check", headers=_bearer(owner_token))
    assert old_check.status_code == 200
    assert old_check.json()["role"] == "member"

    new_check = client.get("/api/auth/check", headers=_bearer(member_token))
    assert new_check.status_code == 200
    assert new_check.json()["role"] == "owner"

    old_owner_denied = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(owner_token),
        json={"role": "member"},
    )
    assert old_owner_denied.status_code == 403
    assert old_owner_denied.json()["error"] == "permission_denied"

    new_owner_allowed = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(member_token),
        json={"role": "viewer"},
    )
    assert new_owner_allowed.status_code == 201, new_owner_allowed.json()

    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == ledger_id))
        target = db.scalar(select(LedgerMember).where(LedgerMember.id == member_id))
        assert ledger is not None and target is not None
        assert ledger.owner_account_id == target.account_id

    audit = client.get(f"/api/ledgers/{ledger_id}/audit", headers=_bearer(member_token))
    assert audit.status_code == 200, audit.json()
    transfer_rows = [row for row in audit.json()["items"] if row["action"] == "owner_transferred"]
    assert len(transfer_rows) == 1
    assert transfer_rows[0]["previous_role"] == "member"
    assert transfer_rows[0]["new_role"] == "owner"


def test_owner_transfer_invalid_target_does_not_change_owner(client: TestClient) -> None:
    ledger_id = _create_family_ledger(client)
    owner_token = _switch_to(client, ledger_id, app_headers())
    invite_token = _mint_invitation(client, ledger_id, owner_token)
    _accept_invitation(client, invite_token, account_name="妹妹")

    members = client.get(f"/api/ledgers/{ledger_id}/members", headers=_bearer(owner_token)).json()["members"]
    owner_id = next(row for row in members if row["role"] == "owner")["member_id"]
    member_id = next(row for row in members if row["role"] == "member")["member_id"]

    self_transfer = client.post(
        f"/api/ledgers/{ledger_id}/members/{owner_id}/transfer-owner",
        headers=_bearer(owner_token),
    )
    assert self_transfer.status_code == 409
    assert self_transfer.json()["error"] in {"owner_transfer_self", "owner_transfer_target_invalid"}
    assert _active_owner_count(ledger_id) == 1

    disable = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/disable",
        headers=_bearer(owner_token),
    )
    assert disable.status_code == 200, disable.json()
    disabled_transfer = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
        headers=_bearer(owner_token),
    )
    assert disabled_transfer.status_code == 404
    assert disabled_transfer.json()["error"] == "member_not_found"
    assert _active_owner_count(ledger_id) == 1

    audit = client.get(f"/api/ledgers/{ledger_id}/audit", headers=_bearer(owner_token))
    assert audit.status_code == 200, audit.json()
    assert all(row["action"] != "owner_transferred" for row in audit.json()["items"])
