"""Real cookie, database, role and device consequences of Web self-service."""

from __future__ import annotations

import re
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import Account, AuthToken, Device, LedgerMember, PairingCode, UploadLink
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from app.services.time_service import now_utc
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, html
    return match.group(1)


def _session_device(token: str) -> tuple[int, int, str]:
    with SessionLocal() as db:
        session = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        device = db.get(Device, session.device_id)
        return session.account_id, device.id, device.public_id


@pytest.fixture
def browser(client, identity):
    token = mint_session(client, identity=identity)
    with closing(public_client()) as browser:
        browser.cookies.set(SESSION_COOKIE_NAME, token)
        yield browser, token


def _post(browser, path: str, **data):
    page = browser.get("/web/settings")
    assert page.status_code == 200, page.text
    return browser.post(path, data={"csrf_token": _csrf(page.text), **data},
                        headers={"Origin": f"https://{PUBLIC_HOST}"}, follow_redirects=False)


@pytest.mark.parametrize("role", ["owner", "member", "viewer"])
def test_each_role_can_find_settings_and_rename_its_own_device(browser, role):
    web, token = browser
    account_id, device_id, public_id = _session_device(token)
    with SessionLocal() as db:
        db.scalar(select(LedgerMember).where(LedgerMember.account_id == account_id,
                                            LedgerMember.ledger_id == "owner")).role = role
        db.commit()
    home = web.get("/web/pending")
    assert 'href="/web/settings"' in home.text
    page = web.get("/web/settings")
    assert "我的设备" in page.text and "当前设备" in page.text
    assert token not in page.text and hash_secret(token) not in page.text
    response = _post(web, f"/web/settings/devices/{public_id}/rename", device_name="书房浏览器")
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        assert db.get(Device, device_id).device_name == "书房浏览器"
    assert "书房浏览器" in web.get(response.headers["location"]).text


def test_unconfirmed_or_current_device_revoke_has_no_effect(browser):
    web, token = browser
    _, device_id, public_id = _session_device(token)
    path = f"/web/settings/devices/{public_id}/revoke"
    assert _post(web, path).status_code == 422
    assert _post(web, path, confirmed="yes").status_code == 409
    with SessionLocal() as db:
        assert db.get(Device, device_id).revoked_at is None
        assert db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token))).revoked_at is None


def test_device_mutation_rejects_foreign_account_and_missing_csrf(browser):
    web, token = browser
    _, device_id, public_id = _session_device(token)
    with SessionLocal() as db:
        foreign = Account(display_name="另一个人", created_at=now_utc())
        db.add(foreign)
        db.flush()
        device = Device(account_id=foreign.id, device_name="不属于我", platform="web")
        db.add(device)
        db.commit()
        foreign_id = device.public_id
    assert foreign_id not in web.get("/web/settings").text
    denied = _post(web, f"/web/settings/devices/{foreign_id}/rename", device_name="越权更名")
    assert denied.status_code == 404
    missing = web.post(f"/web/settings/devices/{public_id}/rename", data={"device_name": "不该保存"},
                       headers={"Origin": f"https://{PUBLIC_HOST}"})
    assert missing.status_code == 403
    with SessionLocal() as db:
        assert db.get(Device, device_id).device_name != "不该保存"
        assert db.scalar(select(Device).where(Device.public_id == foreign_id)).device_name == "不属于我"


def test_invalid_rename_keeps_the_draft_and_saved_device_name(browser):
    web, token = browser
    _, device_id, public_id = _session_device(token)
    draft = "我的长名字" * 30
    response = _post(web, f"/web/settings/devices/{public_id}/rename", device_name=draft)
    assert response.status_code == 422
    assert f'value="{draft}"' in response.text
    assert 'class="settings-device-actions" open' in response.text
    with SessionLocal() as db:
        assert db.get(Device, device_id).device_name == "pytest browser"


def test_revocation_stops_credentials_and_uploads_and_delete_requires_revoked_state(browser, client, identity):
    web, _ = browser
    spare_token = mint_session(client, identity=identity)
    account_id, device_id, public_id = _session_device(spare_token)
    with SessionLocal() as db:
        link = UploadLink(token_hash=hash_secret("web-settings-upload"), account_id=account_id,
                          device_id=device_id, ledger_id="owner")
        db.add(link)
        db.commit()
        link_id = link.id
    assert _post(web, f"/web/settings/devices/{public_id}/delete", confirmed="yes").status_code == 409
    result = _post(web, f"/web/settings/devices/{public_id}/revoke", confirmed="yes")
    assert result.status_code == 303, result.text
    with SessionLocal() as db:
        assert db.get(Device, device_id).revoked_at is not None
        assert db.get(UploadLink, link_id).revoked_at is not None
        assert db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(spare_token))).revoked_at is not None
    with closing(public_client()) as old:
        old.cookies.set(SESSION_COOKIE_NAME, spare_token)
        assert old.get("/web/settings", follow_redirects=False).headers["location"].startswith("/web/auth/login")
    removed = _post(web, f"/web/settings/devices/{public_id}/delete", confirmed="yes")
    assert removed.status_code == 303, removed.text
    with SessionLocal() as db:
        assert db.get(Device, device_id) is None
        assert db.get(UploadLink, link_id) is None


def test_lost_membership_keeps_self_service_but_does_not_mint_pairing_codes(browser):
    web, token = browser
    account_id, device_id, public_id = _session_device(token)
    with SessionLocal() as db:
        for member in db.scalars(select(LedgerMember).where(LedgerMember.account_id == account_id)):
            member.disabled_at = now_utc()
        count_before = len(list(db.scalars(select(PairingCode.id))))
        db.commit()
    picker = web.get("/web/auth/ledgers")
    assert picker.status_code == 409 and 'href="/web/settings"' in picker.text
    page = web.get("/web/settings")
    assert page.status_code == 200 and "账户已连接" in page.text
    assert "生成新设备连接码" not in page.text
    changed = _post(web, f"/web/settings/devices/{public_id}/rename", device_name="仍是我的浏览器")
    assert changed.status_code == 303
    refused = _post(web, "/web/settings/devices/pairing-codes")
    assert refused.status_code == 409 and "选择一个仍有访问权限的账本" in refused.text
    with SessionLocal() as db:
        assert db.get(Device, device_id).device_name == "仍是我的浏览器"
        assert len(list(db.scalars(select(PairingCode.id)))) == count_before


def test_browser_recovery_retains_device_identity_and_reveals_code_only_once(browser, client, identity):
    web, _ = browser
    spare_token = mint_session(client, identity=identity)
    _, device_id, public_id = _session_device(spare_token)
    assert _post(web, f"/web/settings/devices/{public_id}/revoke", confirmed="yes").status_code == 303
    created = _post(web, "/web/settings/devices/pairing-codes", recovery_device_public_id=public_id, confirmed="yes")
    assert created.status_code == 200, created.text
    match = re.search(r'value="([0-9]{8})" data-settings-code', created.text)
    assert match is not None
    code = match.group(1)
    assert created.text.count(code) == 1 and created.headers["cache-control"] == "no-store"
    assert "data-qr-output" not in created.text
    assert "data-settings-code>" not in web.get("/web/settings").text
    assert _post(web, f"/web/settings/devices/{public_id}/delete", confirmed="yes").status_code == 409
    with closing(public_client()) as recovered:
        form = recovered.get("/web/auth/login")
        result = recovered.post("/web/auth/login", data={"csrf_token": _csrf(form.text),
            "pairing_code": code, "device_name": "重新连接的浏览器"},
            headers={"Origin": f"https://{PUBLIC_HOST}"}, follow_redirects=False)
        assert result.status_code == 303, result.text
        fresh_token = recovered.cookies.get(SESSION_COOKIE_NAME)
        assert _session_device(fresh_token)[1] == device_id
    with SessionLocal() as db:
        assert db.get(Device, device_id).revoked_at is None


def test_new_device_qr_uses_one_time_result_and_existing_pairing_authority(browser, monkeypatch):
    web, token = browser
    account_id, original_device_id, _ = _session_device(token)
    monkeypatch.setenv("PUBLIC_BASE_URL", f"https://{PUBLIC_HOST}")
    get_settings.cache_clear()
    try:
        created = _post(web, "/web/settings/devices/pairing-codes")
        assert created.status_code == 200, created.text
        code = re.search(r'value="([0-9]{8})" data-settings-code', created.text).group(1)
        assert created.text.count(code) == 1
        assert 'data-qr-source="[data-settings-code]"' in created.text
        assert f'data-qr-origin="https://{PUBLIC_HOST}"' in created.text
        assert created.headers["cache-control"] == "no-store"
        assert "data-qr-output" not in web.get("/web/settings").text
        with closing(public_client()) as new_device:
            form = new_device.get("/web/auth/login")
            assert "/static/web/auth-pairing.js" in form.text
            result = new_device.post("/web/auth/login", data={"csrf_token": _csrf(form.text),
                "pairing_code": code, "device_name": "扫码连接的 iPad"},
                headers={"Origin": f"https://{PUBLIC_HOST}"}, follow_redirects=False)
            assert result.status_code == 303, result.text
            paired_account, paired_device, _ = _session_device(new_device.cookies.get(SESSION_COOKIE_NAME))
            assert paired_account == account_id and paired_device != original_device_id
        with SessionLocal() as db:
            assert db.get(Device, original_device_id).revoked_at is None
            assert db.scalar(select(PairingCode).where(PairingCode.code_hash == hash_secret(code))).used_at is not None
    finally:
        get_settings.cache_clear()


def test_desktop_bridge_settings_keep_device_identity_without_ledger(browser):
    _, token = browser
    account_id, device_id, public_id = _session_device(token)
    with SessionLocal() as db:
        db.get(Device, device_id).platform = "desktop"
        for member in db.scalars(select(LedgerMember).where(LedgerMember.account_id == account_id)):
            member.disabled_at = now_utc()
        db.commit()
    with closing(TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 52000))) as desktop:
        headers = {"Authorization": f"Bearer {token}", "X-Ticketbox-Desktop-Bridge": "v1"}
        page = desktop.get("/web/settings", headers=headers)
        assert page.status_code == 200 and public_id in page.text
        assert 'action="/web/auth/logout"' not in page.text
        renamed = desktop.post(f"/web/settings/devices/{public_id}/rename", data={
            "csrf_token": _csrf(page.text), "device_name": "我的管理器"},
            headers={**headers, "Origin": "http://127.0.0.1:8000"}, follow_redirects=False)
        assert renamed.status_code == 303, renamed.text
    with SessionLocal() as db:
        assert db.get(Device, device_id).device_name == "我的管理器"
