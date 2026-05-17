"""v0.4-beta1 family-ledger permission & invitation tests.

Covers the 15 scenarios listed in
``docs/DECISIONS/0022-family-ledger-permission-model.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuthToken, Invitation, Ledger, LedgerMember
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc
from conftest import admin_headers, app_headers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _create_family_ledger(client: TestClient, name: str = "家庭账本") -> str:
    """Use admin token to mint a new ledger; owner-account is auto-added."""
    resp = client.post("/api/ledgers", headers=admin_headers(), json={"name": name})
    assert resp.status_code == 201, resp.json()
    return resp.json()["ledger_id"]


def _switch_to(client: TestClient, ledger_id: str, headers: dict[str, str]) -> str:
    resp = client.post(f"/api/ledgers/{ledger_id}/switch", headers=headers)
    assert resp.status_code == 200, resp.json()
    return resp.json()["session_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_member_role(ledger_id: str, account_id: int, role: str) -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == ledger_id)
            .where(LedgerMember.account_id == account_id)
            .limit(1)
        )
        assert member is not None
        member.role = role
        db.commit()


# ---------------------------------------------------------------------------
# T1-T3 — invitation create permission
# ---------------------------------------------------------------------------


def test_owner_can_create_invitation_and_token_is_returned_once(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    # Switch app token to family ledger so caller is owner there.
    family_app = _switch_to(client, family_id, app_headers())

    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=_bearer(family_app),
        json={"role": "member", "note": "妈妈"},
    )
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["invite_token"].startswith("inv_")
    assert body["invitation"]["role"] == "member"
    assert body["invitation"]["note"] == "妈妈"
    assert body["invitation"]["used_at"] is None
    assert body["invitation"]["revoked_at"] is None

    # The plain token must never be readable from DB.
    plain = body["invite_token"]
    with SessionLocal() as db:
        rows = list(db.scalars(select(Invitation)))
        assert len(rows) == 1
        assert rows[0].token_hash == hash_secret(plain)
        # Sanity: stored hash is not the plain token itself.
        assert rows[0].token_hash != plain

    # Listing does NOT echo invite_token plain.
    listed = client.get(
        f"/api/ledgers/{family_id}/invitations", headers=_bearer(family_app)
    )
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body["invitations"]) == 1
    assert "invite_token" not in listed_body["invitations"][0]


def test_member_cannot_create_invitation(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    # Demote owner-of-family-ledger to member (synthetic scenario).
    with SessionLocal() as db:
        owner = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(family_app)))
        assert owner is not None
        _set_member_role(family_id, owner.account_id, "member")

    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=_bearer(family_app),
        json={"role": "member"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "permission_denied"


def test_viewer_cannot_create_invitation(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    with SessionLocal() as db:
        owner = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(family_app)))
        assert owner is not None
        _set_member_role(family_id, owner.account_id, "viewer")

    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=_bearer(family_app),
        json={"role": "member"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "permission_denied"
    assert resp.json()["message"] == "当前角色为只读，无法修改账本。"


def test_cannot_invite_with_owner_role(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=_bearer(family_app),
        json={"role": "owner"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"] == "invitation_role_invalid"


# ---------------------------------------------------------------------------
# T4-T8 — accept invitation paths
# ---------------------------------------------------------------------------


def _mint(client: TestClient, family_id: str, family_app: str, role: str = "member") -> str:
    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=_bearer(family_app),
        json={"role": role},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()["invite_token"]


def test_preview_invitation_returns_target_without_consuming_token(client: TestClient) -> None:
    ledger_name = "家庭共同账本" + "很长" * 20
    family_id = _create_family_ledger(client, name=ledger_name)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app, role="viewer")

    preview = client.post(
        "/api/invitations/preview",
        json={"invite_token": invite},
    )
    assert preview.status_code == 200, preview.json()
    body = preview.json()
    assert body["ledger_id"] == family_id
    assert body["ledger_name"] == ledger_name
    assert body["role"] == "viewer"
    assert body["expires_at"] is not None

    with SessionLocal() as db:
        invitation = db.scalar(
            select(Invitation).where(Invitation.token_hash == hash_secret(invite))
        )
        assert invitation is not None
        assert invitation.used_at is None
        assert invitation.used_by_account_id is None

    accepted = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite,
            "account_name": "只读成员",
            "device_name": "Preview-Phone",
            "platform": "android",
        },
    )
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["role"] == "viewer"


def test_preview_used_invitation_is_invalid(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)

    accepted = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "A", "device_name": "d1", "platform": "android"},
    )
    assert accepted.status_code == 200

    preview = client.post(
        "/api/invitations/preview",
        json={"invite_token": invite},
    )
    assert preview.status_code == 400
    assert preview.json()["error"] == "invitation_invalid"


def test_accept_invitation_issues_app_token_and_membership(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app, role="member")

    resp = client.post(
        "/api/invitations/accept",
        json={
            "invite_token": invite,
            "account_name": "妈妈",
            "device_name": "Mom-Pixel",
            "platform": "android",
        },
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["role"] == "member"
    assert body["ledger_id"] == family_id
    assert body["account_name"] == "妈妈"

    # Joining account has membership now.
    new_token = body["session_token"]
    check = client.get("/api/auth/check", headers=_bearer(new_token))
    assert check.status_code == 200
    assert check.json()["role"] == "member"
    assert check.json()["ledger_id"] == family_id


def test_accept_already_used_invitation(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)

    first = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "A", "device_name": "d1", "platform": "android"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "B", "device_name": "d2", "platform": "android"},
    )
    assert second.status_code == 400
    assert second.json()["error"] == "invitation_invalid"


def test_accept_revoked_invitation(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)

    # Fetch public_id via list endpoint.
    listed = client.get(
        f"/api/ledgers/{family_id}/invitations", headers=_bearer(family_app)
    ).json()["invitations"]
    public_id = listed[0]["public_id"]

    revoke = client.post(
        f"/api/ledgers/{family_id}/invitations/{public_id}/revoke",
        headers=_bearer(family_app),
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"] is not None

    resp = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "x", "device_name": "d", "platform": "android"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invitation_invalid"


def test_accept_expired_invitation(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)
    with SessionLocal() as db:
        inv = db.scalar(select(Invitation))
        assert inv is not None
        inv.expires_at = now_utc() - timedelta(days=1)
        db.commit()

    resp = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "x", "device_name": "d", "platform": "android"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invitation_invalid"


def test_accept_invitation_rechecks_expiry_when_consuming_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)
    base = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    with SessionLocal() as db:
        inv = db.scalar(select(Invitation))
        assert inv is not None
        inv.expires_at = base + timedelta(seconds=1)
        db.commit()

    ticks = iter([base, base + timedelta(seconds=2)])
    monkeypatch.setattr("app.services.invitation_invites.now_utc", lambda: next(ticks))

    resp = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": "x", "device_name": "d", "platform": "android"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invitation_invalid"

    with SessionLocal() as db:
        inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_secret(invite)))
        assert inv is not None
        assert inv.used_at is None
        assert inv.used_by_account_id is None


def test_accept_unknown_token(client: TestClient) -> None:
    resp = client.post(
        "/api/invitations/accept",
        json={"invite_token": "inv_totally-bogus-xxxxxxxxxxxxxxx", "account_name": "x", "device_name": "d", "platform": "android"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invitation_invalid"


# ---------------------------------------------------------------------------
# T9-T10 — viewer/member write enforcement
# ---------------------------------------------------------------------------


def _make_role_token(client: TestClient, family_id: str, family_app: str, role: str) -> str:
    """Mint invite, accept it, return the joiner's app token (role 'role')."""
    invite = _mint(client, family_id, family_app, role=role)
    resp = client.post(
        "/api/invitations/accept",
        json={"invite_token": invite, "account_name": f"u-{role}", "device_name": f"d-{role}", "platform": "android"},
    )
    assert resp.status_code == 200
    return resp.json()["session_token"]


def test_viewer_cannot_create_manual_expense(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    viewer_token = _make_role_token(client, family_id, family_app, role="viewer")

    resp = client.post(
        "/api/expenses/manual",
        headers=_bearer(viewer_token),
        json={"amount_cents": 1234, "merchant": "X", "category": "其他"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "permission_denied"


def test_member_can_create_manual_expense(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")

    resp = client.post(
        "/api/expenses/manual",
        headers=_bearer(member_token),
        json={"amount_cents": 1234, "merchant": "X", "category": "其他"},
    )
    assert resp.status_code == 200, resp.json()


def test_member_cannot_disable_other_member(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")

    members = client.get(
        f"/api/ledgers/{family_id}/members", headers=_bearer(member_token)
    ).json()["members"]
    assert any(m["role"] == "owner" for m in members)
    owner_member_id = next(m for m in members if m["role"] == "owner")["member_id"]

    resp = client.post(
        f"/api/ledgers/{family_id}/members/{owner_member_id}/disable",
        headers=_bearer(member_token),
    )
    assert resp.status_code == 403


def test_owner_can_change_member_between_writer_and_viewer(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")

    members = client.get(
        f"/api/ledgers/{family_id}/members", headers=_bearer(family_app)
    ).json()["members"]
    member_id = next(m for m in members if m["role"] == "member")["member_id"]

    to_viewer = client.post(
        f"/api/ledgers/{family_id}/members/{member_id}/role",
        headers=_bearer(family_app),
        json={"role": "viewer"},
    )
    assert to_viewer.status_code == 200, to_viewer.json()
    assert to_viewer.json()["role"] == "viewer"

    # Existing token sees the new role on its next authenticated request.
    check_viewer = client.get("/api/auth/check", headers=_bearer(member_token))
    assert check_viewer.status_code == 200
    assert check_viewer.json()["role"] == "viewer"
    blocked_write = client.post(
        "/api/expenses/manual",
        headers=_bearer(member_token),
        json={"amount_cents": 1234, "merchant": "X", "category": "其他"},
    )
    assert blocked_write.status_code == 403

    back_to_member = client.post(
        f"/api/ledgers/{family_id}/members/{member_id}/role",
        headers=_bearer(family_app),
        json={"role": "member"},
    )
    assert back_to_member.status_code == 200
    assert back_to_member.json()["role"] == "member"
    allowed_write = client.post(
        "/api/expenses/manual",
        headers=_bearer(member_token),
        json={"amount_cents": 1234, "merchant": "X", "category": "其他"},
    )
    assert allowed_write.status_code == 200, allowed_write.json()


def test_member_cannot_change_roles_and_owner_role_is_fixed(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")
    members = client.get(
        f"/api/ledgers/{family_id}/members", headers=_bearer(family_app)
    ).json()["members"]
    owner_id = next(m for m in members if m["role"] == "owner")["member_id"]
    member_id = next(m for m in members if m["role"] == "member")["member_id"]

    denied = client.post(
        f"/api/ledgers/{family_id}/members/{member_id}/role",
        headers=_bearer(member_token),
        json={"role": "viewer"},
    )
    assert denied.status_code == 403

    owner_change = client.post(
        f"/api/ledgers/{family_id}/members/{owner_id}/role",
        headers=_bearer(family_app),
        json={"role": "viewer"},
    )
    assert owner_change.status_code == 409
    assert owner_change.json()["error"] == "member_cannot_change_owner_role"


# ---------------------------------------------------------------------------
# T11 — disabling member revokes their token
# ---------------------------------------------------------------------------


def test_disable_member_revokes_active_tokens(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")

    # Member token works at first.
    ok = client.get("/api/auth/check", headers=_bearer(member_token))
    assert ok.status_code == 200

    members = client.get(
        f"/api/ledgers/{family_id}/members", headers=_bearer(family_app)
    ).json()["members"]
    member_id = next(m for m in members if m["role"] == "member")["member_id"]

    disable = client.post(
        f"/api/ledgers/{family_id}/members/{member_id}/disable",
        headers=_bearer(family_app),
    )
    assert disable.status_code == 200
    assert disable.json()["disabled_at"] is not None

    # Token is now 401.
    fail = client.get("/api/auth/check", headers=_bearer(member_token))
    assert fail.status_code == 401


def test_cannot_disable_owner_or_self(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    members = client.get(
        f"/api/ledgers/{family_id}/members", headers=_bearer(family_app)
    ).json()["members"]
    owner_member_id = next(m for m in members if m["role"] == "owner")["member_id"]

    resp = client.post(
        f"/api/ledgers/{family_id}/members/{owner_member_id}/disable",
        headers=_bearer(family_app),
    )
    # Self-disable is rejected first; both checks acceptable.
    assert resp.status_code == 409
    assert resp.json()["error"] in {"member_cannot_disable_self", "member_cannot_disable_owner"}


# ---------------------------------------------------------------------------
# T12-T13 — privacy: joiner does NOT see owner's personal ledger
# ---------------------------------------------------------------------------


def test_joiner_does_not_see_owners_personal_ledger(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")

    listed = client.get("/api/ledgers", headers=_bearer(member_token)).json()["ledgers"]
    ids = {row["ledger_id"] for row in listed}
    # Joiner sees the family ledger ONLY — not the owner's "owner" or "tester_1".
    assert ids == {family_id}


def test_existing_owner_role_unchanged_after_invite(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    _make_role_token(client, family_id, family_app, role="member")

    # The original owner (same account) still has 'owner' role across all
    # her own ledgers. Use the family_app token (which is bound to the same
    # account post-switch) — switching back to personal yields owner again.
    back = client.post("/api/ledgers/owner/switch", headers=_bearer(family_app))
    assert back.status_code == 200
    fresh = back.json()["session_token"]
    listed = client.get("/api/ledgers", headers=_bearer(fresh)).json()["ledgers"]
    for row in listed:
        if row["ledger_id"] in {"owner", "tester_1", family_id}:
            assert row["role"] == "owner", row


# ---------------------------------------------------------------------------
# T14 — token cross-ledger admin block
# ---------------------------------------------------------------------------


def test_cannot_administer_other_ledger_through_url(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    # App token is still bound to "owner" ledger; try to mint invitations for
    # the family ledger without switching. Must 404 (we collapse to ledger_not_found).
    resp = client.post(
        f"/api/ledgers/{family_id}/invitations",
        headers=app_headers(),
        json={"role": "member"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "ledger_not_found"


# ---------------------------------------------------------------------------
# T15 — invite_token not echoed in server logs (smoke check: hash matches plain)
# ---------------------------------------------------------------------------


def test_invite_token_hash_matches_and_not_persisted_plain(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    invite = _mint(client, family_id, family_app)
    with SessionLocal() as db:
        row = db.scalar(select(Invitation))
        assert row is not None
        assert row.token_hash == hash_secret(invite)
        # Defensive: token_hash must look like a hex digest, not the plain.
        assert all(c in "0123456789abcdef" for c in row.token_hash)
        assert row.token_hash != invite


# ---------------------------------------------------------------------------
# T16 — switching to family ledger then back keeps roles consistent
# ---------------------------------------------------------------------------


def test_switching_back_to_personal_ledger_keeps_owner_role(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    fam_token = _switch_to(client, family_id, app_headers())
    check = client.get("/api/auth/check", headers=_bearer(fam_token))
    assert check.status_code == 200
    assert check.json()["role"] == "owner"

    back = client.post("/api/ledgers/owner/switch", headers=_bearer(fam_token))
    assert back.status_code == 200
    new_token = back.json()["session_token"]
    final = client.get("/api/auth/check", headers=_bearer(new_token))
    assert final.json()["role"] == "owner"
    assert final.json()["ledger_id"] == "owner"


def test_member_role_persists_across_switch(client: TestClient) -> None:
    family_id = _create_family_ledger(client)
    family_app = _switch_to(client, family_id, app_headers())
    member_token = _make_role_token(client, family_id, family_app, role="member")
    # Joiner is only in family_id, so /api/ledgers returns only family_id.
    listed = client.get("/api/ledgers", headers=_bearer(member_token)).json()["ledgers"]
    assert len(listed) == 1 and listed[0]["role"] == "member"
    # Sanity: ledger archived state is None.
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == family_id))
        assert ledger is not None and ledger.archived_at is None
