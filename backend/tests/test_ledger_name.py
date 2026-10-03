"""One ledger-label command across API, Web and local Owner management."""

import re
from contextlib import closing

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Account, AuthToken, Device, Ledger, LedgerAuditLog, LedgerMember
from app.routes import owner_ledgers
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import authenticate_session_token, hash_secret
from app.services.ledger_service import rename_ledger
from app.services.time_service import now_utc
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


def _current(client, identity, ledger_id="owner"):
    return next(row for row in client.get("/api/ledgers", headers=identity.app_headers).json()["ledgers"]
                if row["ledger_id"] == ledger_id)


def test_rename_keeps_financial_fact_calendar_credentials_and_one_audit_on_retry(client, identity):
    current = _current(client, identity)
    calendar = client.get("/api/ledgers/owner/calendar", headers=identity.app_headers).json()
    created = client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"client_ref": "name-fact", "amount_cents": 1234, "home_currency_code": "CNY",
              "time_input": {"precision": "date_only", "calendar_revision": calendar["revision"],
                             "user_local_date": "2026-04-30"}})
    assert created.status_code == 200, created.text
    fact_path = f"/api/expenses/{created.json()['id']}"
    original = client.get(fact_path, headers=identity.app_headers).json()
    payload = {"name": "我们的家庭账本", "expected_name": current["name"]}
    for _ in range(2):
        saved = client.post("/api/ledgers/owner/name", headers=identity.app_headers, json=payload)
        assert saved.status_code == 200 and saved.json() == {**current, "name": payload["name"]}
    assert client.get(fact_path, headers=identity.app_headers).json() == original
    assert client.get("/api/ledgers/owner/calendar", headers=identity.app_headers).json() == calendar
    assert client.get("/api/settings/server", headers=identity.app_headers).json()["ledger_name"] == payload["name"]
    with SessionLocal() as db:
        actor = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(identity.app_token)))
        logs = list(db.scalars(select(LedgerAuditLog).where(LedgerAuditLog.action == "ledger_renamed")))
        assert len(logs) == 1 and logs[0].actor_account_id == actor.account_id
        assert current["name"] in logs[0].detail and payload["name"] in logs[0].detail
        assert actor.revoked_at is None


def test_stale_name_is_not_applied_and_other_owned_ledger_does_not_switch_session(client, identity):
    selected = _current(client, identity)
    other = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": "另一账本"}).json()
    path = f"/api/ledgers/{other['ledger_id']}/name"
    assert client.post(path, headers=identity.app_headers,
        json={"name": "旅行", "expected_name": "另一账本"}).status_code == 200
    stale = client.post(path, headers=identity.app_headers, json={"name": "旧输入", "expected_name": "另一账本"})
    assert stale.status_code == 409
    assert _current(client, identity, other["ledger_id"])["name"] == "旅行"
    assert _current(client, identity) == selected
    assert client.get("/api/settings/server", headers=identity.app_headers).json()["ledger_id"] == "owner"


@pytest.mark.parametrize("role", ["member", "viewer", "mismatched_owner"])
def test_only_the_actual_owner_may_rename(client, identity, role):
    current = _current(client, identity)
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
                                                      LedgerMember.account_id == ledger.owner_account_id))
        if role == "mismatched_owner":
            other = Account(display_name="另一拥有者")
            db.add(other)
            db.flush()
            ledger.owner_account_id = other.id
        else:
            member.role = role
        db.commit()
    denied = client.post("/api/ledgers/owner/name", headers=identity.app_headers,
                         json={"name": "不能保存", "expected_name": current["name"]})
    assert denied.status_code == 403
    assert _current(client, identity)["name"] == current["name"]


def test_invalid_foreign_and_archived_targets_cannot_change_a_label(client, identity):
    current = _current(client, identity)
    for name in (" ", "x" * 61):
        assert client.post("/api/ledgers/owner/name", headers=identity.app_headers,
                           json={"name": name, "expected_name": current["name"]}).status_code == 422
    with SessionLocal() as db:
        outsider = Account(display_name="别人的账号")
        db.add(outsider)
        db.flush()
        db.add(Ledger(ledger_id="private-ledger", name="别人的账本", owner_account_id=outsider.id))
        db.commit()
    denied = client.post("/api/ledgers/private-ledger/name", headers=identity.app_headers,
                         json={"name": "不能改", "expected_name": "别人的账本"})
    assert denied.status_code in (403, 404)
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        ledger.archived_at = now_utc()
        db.commit()
    assert client.post("/api/ledgers/owner/name", headers=identity.app_headers,
                       json={"name": "已归档不能改", "expected_name": current["name"]}).status_code in (403, 404)


def test_web_conflict_keeps_input_refreshes_baseline_and_requires_an_explicit_save(client, identity):
    token = mint_session(client, identity=identity)
    old = _current(client, identity)["name"]
    with closing(public_client()) as web:
        web.cookies.set(SESSION_COOKIE_NAME, token)
        page = web.get("/web/family")
        assert page.status_code == 200
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        assert client.post("/api/ledgers/owner/name", headers=identity.app_headers,
                           json={"name": "另一台设备", "expected_name": old}).status_code == 200
        form = {"name": "我输入的名称", "expected_name": old, "csrf_token": csrf}
        headers = {"Origin": f"https://{PUBLIC_HOST}"}
        conflict = web.post("/web/family/name?ledger_id=owner", data=form, headers=headers)
        assert conflict.status_code == 409 and 'value="我输入的名称"' in conflict.text
        assert 'name="expected_name" value="另一台设备"' in conflict.text
        rejected = web.post("/web/family/name?ledger_id=owner", data={"name": "缺令牌", "expected_name": "另一台设备"}, headers=headers)
        assert rejected.status_code == 403
        saved = web.post("/web/family/name?ledger_id=owner", data={**form, "expected_name": "另一台设备"},
                         headers=headers, follow_redirects=False)
        assert saved.status_code == 303
        assert "我输入的名称" in web.get(saved.headers["location"]).text


def test_owner_uses_same_conflict_rule_and_remains_loopback_only(client, identity):
    old = _current(client, identity)["name"]
    path = "/owner/ledgers/owner/name"
    form = {"name": "电脑上的家", "expected_name": old}
    assert client.post(path, data=form).status_code == 403
    app.dependency_overrides[owner_ledgers._require_local] = lambda: None
    try:
        saved = client.post(path, data=form, follow_redirects=False)
        assert saved.status_code == 303
        conflict = client.post(path, data={**form, "name": "未保存的输入"})
        assert conflict.status_code == 409 and 'value="未保存的输入"' in conflict.text
        assert 'name="expected_name" value="电脑上的家"' in conflict.text
    finally:
        app.dependency_overrides.pop(owner_ledgers._require_local, None)


def test_revocation_after_authentication_cannot_publish_a_ledger_name(client, identity):
    old = _current(client, identity)["name"]
    with SessionLocal() as command:
        auth = authenticate_session_token(command, identity.app_token, {"app"}, selected_ledger_id="owner")
        with SessionLocal() as revoker:
            revoker.get(Device, auth.device_id).revoked_at = now_utc()
            revoker.commit()
        with pytest.raises(AppError) as failure:
            rename_ledger(command, account_id=auth.account_id, ledger_id="owner", name="不能保存",
                          expected_name=old, auth=auth)
        assert failure.value.status_code == 401
        command.rollback()
        assert command.scalar(select(Ledger).where(Ledger.ledger_id == "owner")).name == old


def test_owner_access_loss_keeps_unpublished_name_without_offering_another_ledger(client, identity):
    old = _current(client, identity)["name"]
    with SessionLocal() as db:
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == "owner"))
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
            LedgerMember.account_id == ledger.owner_account_id))
        member.role = "member"
        db.commit()
    app.dependency_overrides[owner_ledgers._require_local] = lambda: None
    try:
        rejected = client.post("/owner/ledgers/owner/name", data={"name": "尚未保存的家", "expected_name": old})
        assert rejected.status_code == 403
        assert 'value="尚未保存的家" readonly' in rejected.text
        assert 'action="/owner/ledgers/owner/name"' not in rejected.text
        with SessionLocal() as db:
            assert db.scalar(select(Ledger.name).where(Ledger.ledger_id == "owner")) == old
    finally:
        app.dependency_overrides.pop(owner_ledgers._require_local, None)
