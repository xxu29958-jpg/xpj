from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import AuthToken, Ledger, LedgerAuditLog, LedgerMember
from app.services.identity_service import hash_secret


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_family_ledger(client: TestClient, name: str = "家庭账本", *, identity) -> str:
    resp = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": name})
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


def _assert_permission_denied(response, *, label: str) -> None:
    assert response.status_code == 403, label
    assert response.json()["error"] == "permission_denied", label


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


def test_family_member_audit_records_sensitive_safe_actions(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)

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


def test_owner_transfer_keeps_single_owner_and_demotes_previous_owner(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)
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

    new_owner_role_change = client.post(
        f"/api/ledgers/{ledger_id}/members/{body['previous_owner']['member_id']}/role",
        headers=_bearer(member_token),
        json={"role": "viewer"},
    )
    assert new_owner_role_change.status_code == 200, new_owner_role_change.json()
    assert new_owner_role_change.json()["role"] == "viewer"

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


def test_owner_transfer_revokes_demoted_owner_admin_tokens(client: TestClient, *, identity) -> None:
    ledger_id = "owner"
    invite_token = _mint_invitation(client, ledger_id, identity.app_headers["Authorization"].removeprefix("Bearer "))
    member_token = _accept_invitation(client, invite_token, account_name="新 owner")
    member_id = _member_id_for_role(client, ledger_id, identity.app_headers["Authorization"].removeprefix("Bearer "), "member")

    before = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert before.status_code == 200, before.json()

    transfer = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
        headers=identity.app_headers,
    )
    assert transfer.status_code == 200, transfer.json()

    after = client.post(
        "/api/bootstrap/pairing-codes",
        headers=identity.admin_headers,
        json={"ttl_minutes": 15},
    )
    assert after.status_code == 401
    assert after.json()["error"] == "invalid_token"

    new_owner_allowed = client.post(
        f"/api/ledgers/{ledger_id}/invitations",
        headers=_bearer(member_token),
        json={"role": "viewer"},
    )
    assert new_owner_allowed.status_code == 201, new_owner_allowed.json()


def test_member_and_viewer_cannot_call_owner_member_management(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)

    member_token = _accept_invitation(
        client,
        _mint_invitation(client, ledger_id, owner_token, role="member"),
        account_name="成员",
        device_name="Member-Phone",
    )
    viewer_token = _accept_invitation(
        client,
        _mint_invitation(client, ledger_id, owner_token, role="viewer"),
        account_name="只读",
        device_name="Viewer-Phone",
    )
    member_id = _member_id_for_role(client, ledger_id, owner_token, "member")
    viewer_id = _member_id_for_role(client, ledger_id, owner_token, "viewer")

    for label, token in [("member", member_token), ("viewer", viewer_token)]:
        # Listing members is read access, but management actions remain owner-only.
        listing = client.get(f"/api/ledgers/{ledger_id}/members", headers=_bearer(token))
        assert listing.status_code == 200, listing.json()

        _assert_permission_denied(
            client.post(
                f"/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
                headers=_bearer(token),
            ),
            label=f"{label} transfer owner",
        )
        _assert_permission_denied(
            client.post(
                f"/api/ledgers/{ledger_id}/members/{viewer_id}/role",
                headers=_bearer(token),
                json={"role": "member"},
            ),
            label=f"{label} role change",
        )
        _assert_permission_denied(
            client.post(
                f"/api/ledgers/{ledger_id}/members/{viewer_id}/disable",
                headers=_bearer(token),
            ),
            label=f"{label} disable member",
        )
        _assert_permission_denied(
            client.post(
                f"/api/ledgers/{ledger_id}/invitations",
                headers=_bearer(token),
                json={"role": "member"},
            ),
            label=f"{label} create invitation",
        )
        _assert_permission_denied(
            client.get(f"/api/ledgers/{ledger_id}/audit", headers=_bearer(token)),
            label=f"{label} audit list",
        )

    assert _active_owner_count(ledger_id) == 1


def test_auth_token_role_is_resolved_from_current_ledger_member(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)
    member_token = _accept_invitation(
        client,
        _mint_invitation(client, ledger_id, owner_token, role="member"),
        account_name="角色缓存验证",
    )

    with SessionLocal() as db:
        token_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(member_token)))
        assert token_row is not None
        assert not hasattr(token_row, "role")
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == token_row.account_id)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()

    check_viewer = client.get("/api/auth/check", headers=_bearer(member_token))
    assert check_viewer.status_code == 200
    assert check_viewer.json()["role"] == "viewer"

    with SessionLocal() as db:
        token_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(member_token)))
        assert token_row is not None
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == token_row.account_id)
        )
        assert member is not None
        member.role = "member"
        db.commit()

    check_member = client.get("/api/auth/check", headers=_bearer(member_token))
    assert check_member.status_code == 200
    assert check_member.json()["role"] == "member"


def test_role_downgrade_makes_existing_token_read_only_immediately(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)
    member_token = _accept_invitation(
        client,
        _mint_invitation(client, ledger_id, owner_token, role="member"),
        account_name="降级成员",
    )
    member_id = _member_id_for_role(client, ledger_id, owner_token, "member")

    write_before = client.post(
        "/api/expenses/manual",
        headers=_bearer(member_token),
        json={
            "amount_cents": 1280,
            "merchant": "降级前可写",
            "category": "生活",
            "note": "",
            "expense_time": None,
        },
    )
    assert write_before.status_code == 200, write_before.json()

    changed = client.post(
        f"/api/ledgers/{ledger_id}/members/{member_id}/role",
        headers=_bearer(owner_token),
        json={"role": "viewer"},
    )
    assert changed.status_code == 200, changed.json()

    check = client.get("/api/auth/check", headers=_bearer(member_token))
    assert check.status_code == 200
    assert check.json()["role"] == "viewer"

    read_after = client.get("/api/expenses/confirmed", headers=_bearer(member_token))
    assert read_after.status_code == 200, read_after.json()

    write_after = client.post(
        "/api/expenses/manual",
        headers=_bearer(member_token),
        json={
            "amount_cents": 990,
            "merchant": "降级后不应写入",
            "category": "生活",
            "note": "",
            "expense_time": None,
        },
    )
    _assert_permission_denied(write_after, label="demoted member manual expense")

    _assert_permission_denied(
        client.post(
            f"/api/ledgers/{ledger_id}/members/{member_id}/transfer-owner",
            headers=_bearer(member_token),
        ),
        label="demoted member transfer owner",
    )


def test_owner_transfer_invalid_target_does_not_change_owner(client: TestClient, *, identity) -> None:
    ledger_id = _create_family_ledger(client, identity=identity)
    owner_token = _switch_to(client, ledger_id, identity.app_headers)
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
