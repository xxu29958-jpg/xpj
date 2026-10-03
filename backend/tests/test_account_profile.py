"""Account metadata changes preserve identity and reject stale or foreign writes."""

import re
from contextlib import closing

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import Account, AuthToken, Device, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.account_profile_service import rename_profile
from app.services.identity_service import authenticate_session_principal, hash_secret
from app.services.time_service import now_utc
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


@pytest.mark.parametrize("role", ["owner", "member", "viewer"])
def test_self_rename_changes_the_label_without_rebinding_any_identity(client, identity, role):
    with SessionLocal() as db:
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token)))
        account_id, device_id, token_id = token.account_id, token.device_id, token.id
        public_id = db.get(Account, account_id).public_id
        device_public_id = db.get(Device, device_id).public_id
        membership = db.scalar(select(LedgerMember).where(LedgerMember.account_id == account_id,
                                                         LedgerMember.ledger_id == "owner"))
        membership.role = role
        member_id = membership.id
        db.commit()
    current = client.get("/api/settings/account", headers=identity.app_headers)
    assert current.status_code == 200
    payload = {"display_name": "  家里的小王  ", "expected_name": current.json()["display_name"]}
    saved = client.post("/api/settings/account", headers=identity.app_headers, json=payload)
    assert saved.status_code == 200 and saved.json() == {"account_public_id": public_id, "display_name": "家里的小王"}
    assert client.get("/api/settings/server", headers=identity.app_headers).json()["account_name"] == "家里的小王"
    with SessionLocal() as db:
        assert db.get(Account, account_id).public_id == public_id
        assert db.get(Device, device_id).public_id == device_public_id
        assert db.get(AuthToken, token_id).token_hash == hash_secret(identity.app_token)
        assert db.get(AuthToken, token_id).revoked_at is None
        assert db.get(LedgerMember, member_id).role == role


def test_stale_name_is_rejected_but_response_loss_retry_does_not_reapply(client, identity):
    before = client.get("/api/settings/account", headers=identity.app_headers).json()
    payload = {"display_name": "已保存名称", "expected_name": before["display_name"]}
    assert client.post("/api/settings/account", headers=identity.app_headers, json=payload).status_code == 200
    replay = client.post("/api/settings/account", headers=identity.app_headers, json=payload)
    assert replay.status_code == 200 and replay.json()["display_name"] == "已保存名称"
    stale = client.post("/api/settings/account", headers=identity.app_headers,
                        json={**payload, "display_name": "旧页面的输入"})
    assert stale.status_code == 409
    assert client.get("/api/settings/account", headers=identity.app_headers).json()["display_name"] == "已保存名称"


def test_profile_works_without_membership_but_never_accepts_a_target_account(client, identity):
    with SessionLocal() as db:
        actor = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token)))
        for member in db.scalars(select(LedgerMember).where(LedgerMember.account_id == actor.account_id)):
            member.disabled_at = now_utc()
        foreign = Account(display_name="另一个账号")
        db.add(foreign)
        db.commit()
        foreign_id = foreign.public_id
    current = client.get("/api/settings/account", headers=identity.app_headers)
    assert current.status_code == 200
    payload = {"display_name": "没有账本也能改名", "expected_name": current.json()["display_name"]}
    saved = client.post("/api/settings/account", headers=identity.app_headers, json=payload)
    assert saved.status_code == 200
    foreign_write = client.post("/api/settings/account", headers=identity.app_headers,
                                json={**payload, "account_public_id": foreign_id})
    assert foreign_write.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(Account).where(Account.public_id == foreign_id)).display_name == "另一个账号"


def test_web_conflict_preserves_draft_and_requires_an_explicit_save_again(client, identity):
    token = mint_session(client, identity=identity)
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, token)
        page = web.get("/web/settings")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        old_name = client.get("/api/settings/account", headers=identity.app_headers).json()["display_name"]
        changed = client.post("/api/settings/account", headers=identity.app_headers,
                              json={"display_name": "另一台设备的新名称", "expected_name": old_name})
        assert changed.status_code == 200
        headers = {"Origin": f"https://{PUBLIC_HOST}"}
        form = {"csrf_token": csrf, "display_name": "我还没保存的名称", "expected_name": old_name}
        conflict = web.post("/web/settings/account/name", data=form, headers=headers)
        assert conflict.status_code == 409 and 'value="我还没保存的名称"' in conflict.text
        assert 'name="expected_name" value="另一台设备的新名称"' in conflict.text
        assert "账号名称已保存" not in conflict.text
        missing_csrf = web.post("/web/settings/account/name", data={"display_name": "不能保存", "expected_name": old_name}, headers=headers)
        assert missing_csrf.status_code == 403
        saved = web.post("/web/settings/account/name", data={**form, "expected_name": "另一台设备的新名称"},
                         headers=headers, follow_redirects=False)
        assert saved.status_code == 303
        assert "我还没保存的名称" in web.get(saved.headers["location"]).text


@pytest.mark.parametrize("disabled", ["account", "device"])
def test_disabled_account_or_revoked_device_cannot_edit_its_profile(client, identity, disabled):
    before = client.get("/api/settings/account", headers=identity.app_headers).json()
    with SessionLocal() as db:
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token)))
        account_id = token.account_id
        if disabled == "account":
            db.get(Account, account_id).disabled_at = now_utc()
        else:
            db.get(Device, token.device_id).revoked_at = now_utc()
        db.commit()
    denied = client.post("/api/settings/account", headers=identity.app_headers,
                         json={"display_name": "不能改名", "expected_name": before["display_name"]})
    assert denied.status_code == 401
    with SessionLocal() as db:
        assert db.get(Account, account_id).display_name == before["display_name"]


def test_revocation_between_authentication_and_command_cannot_publish_a_name(client, identity):
    with SessionLocal() as command:
        principal = authenticate_session_principal(command, identity.app_token, {"app"})
        with SessionLocal() as revoker:
            revoker.get(Device, principal.device_id).revoked_at = now_utc()
            revoker.commit()
        with pytest.raises(AppError) as failure:
            rename_profile(command, principal, display_name="旧凭据不能保存", expected_name=principal.account_name)
        assert failure.value.status_code == 401
        command.rollback()
        assert command.get(Account, principal.account_id).display_name == principal.account_name
