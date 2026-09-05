"""Installed loopback Web establishes a real Account/Device session."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.middleware import web_session
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import (
    AuthToken,
    Device,
    DeviceEnrollmentAttempt,
    InstallationOwnerClaim,
    LedgerMember,
    PairingCode,
)
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import (
    authenticate_web_session_token,
    hash_secret,
)
from app.services.time_service import now_utc
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    _local_confirmation,
    installed_web_setup,
)

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


def test_installed_loopback_missing_claim_never_falls_back_to_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_session,
        "runtime_settings_service_owned",
        lambda: True,
        raising=False,
    )

    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 51241),
    ) as browser:
        response = browser.get("/web", follow_redirects=False)

    assert response.status_code == 409
    assert response.json()["error"] == "installation_identity_recovery_required"


def test_installed_loopback_starts_with_real_installation_identity_confirmation(
    installed_web: _InstalledWeb,
) -> None:
    entry = installed_web.browser.get("/web", follow_redirects=False)

    assert entry.status_code == 303
    assert entry.headers["location"] == "/web/auth/local?next=%2Fweb"

    preview = installed_web.browser.get(entry.headers["location"])
    assert preview.status_code == 200, preview.text
    assert "确认本机身份" in preview.text
    assert "安装账户" in preview.text
    assert "共同账本" in preview.text
    assert "成员" in preview.text
    assert "共同账本拥有者" not in preview.text
    assert 'action="/web/auth/local"' in preview.text
    assert 'value="shared_household"' in preview.text
    assert 'name="pairing_code"' not in preview.text
    assert 'name="device_name"' not in preview.text


def test_revoked_installation_source_device_blocks_local_browser_enrollment(
    installed_web: _InstalledWeb,
) -> None:
    with SessionLocal() as db:
        claim = db.scalar(select(InstallationOwnerClaim))
        assert claim is not None
        source_device = db.get(Device, claim.device_id)
        assert source_device is not None
        source_device.revoked_at = now_utc()
        db.commit()

    response = installed_web.browser.get("/web/auth/local", follow_redirects=False)

    assert response.status_code == 409
    assert response.json()["error"] == "installation_identity_recovery_required"
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Device).where(Device.platform == "web")
        ) == 0


def test_local_confirmation_mints_web_device_for_installation_account_and_live_role(
    installed_web: _InstalledWeb,
) -> None:
    _, csrf_token, cookie_header = _local_confirmation(installed_web)

    response = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "next": "/web/pending",
        },
        headers={
            "Cookie": cookie_header,
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/web/pending"
    session_token = response.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None

    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        assert token is not None
        device = db.get(Device, token.device_id)
        attempt = db.scalar(select(DeviceEnrollmentAttempt))
        claim = db.scalar(select(InstallationOwnerClaim))
        assert device is not None
        assert attempt is not None
        assert claim is not None
        source = db.get(PairingCode, attempt.pairing_code_id)
        assert source is not None
        assert token.account_id == installed_web.installation_account_id
        assert token.ledger_id == installed_web.shared_ledger_id
        assert device.account_id == installed_web.installation_account_id
        assert device.platform == "web"
        assert source.id != claim.pairing_code_id
        assert source.created_by_device_id == claim.device_id
        assert source.account_id == installed_web.installation_account_id
        assert source.ledger_id == installed_web.shared_ledger_id
        assert source.used_at is not None

        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == installed_web.shared_ledger_id)
            .where(LedgerMember.account_id == installed_web.installation_account_id)
        )
        assert membership is not None
        assert membership.role == "member"

        auth = authenticate_web_session_token(
            db,
            session_token,
            ttl_seconds=8 * 60 * 60,
        ).auth
        assert auth.account_id == installed_web.installation_account_id
        assert auth.device_id == device.id
        assert auth.role == "member"


def test_local_confirmation_response_loss_replays_same_device_and_token(
    installed_web: _InstalledWeb,
) -> None:
    _, csrf_token, cookie_header = _local_confirmation(installed_web)
    request = {
        "csrf_token": csrf_token,
        "ledger_id": installed_web.shared_ledger_id,
        "next": "/web/pending",
    }
    headers = {
        "Cookie": cookie_header,
        "Origin": "http://127.0.0.1:8000",
    }

    first = installed_web.browser.post(
        "/web/auth/local",
        data=request,
        headers=headers,
        follow_redirects=False,
    )
    replay = installed_web.browser.post(
        "/web/auth/local",
        data=request,
        headers=headers,
        follow_redirects=False,
    )

    assert first.status_code == 303, first.text
    assert replay.status_code == 303, replay.text
    first_token = first.cookies.get(SESSION_COOKIE_NAME)
    replay_token = replay.cookies.get(SESSION_COOKIE_NAME)
    assert first_token is not None
    assert replay_token == first_token
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Device).where(Device.platform == "web")
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(DeviceEnrollmentAttempt)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.token_hash == hash_secret(first_token))
        ) == 1


def test_local_confirmation_proof_cannot_change_ledger_target(
    installed_web: _InstalledWeb,
) -> None:
    _, csrf_token, cookie_header = _local_confirmation(installed_web)
    headers = {
        "Cookie": cookie_header,
        "Origin": "http://127.0.0.1:8000",
    }
    first = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": installed_web.shared_ledger_id,
            "next": "/web/pending",
        },
        headers=headers,
        follow_redirects=False,
    )
    changed = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": "owner",
            "next": "/web/pending",
        },
        headers=headers,
        follow_redirects=False,
    )

    assert first.cookies.get(SESSION_COOKIE_NAME) is not None
    assert changed.status_code == 303, changed.text
    assert "error=local_identity_target_changed" in changed.headers["location"]
    assert changed.cookies.get(SESSION_COOKIE_NAME) is None


def test_connected_local_cookie_enters_as_its_real_member_principal(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)

    page = installed_web.browser.get(
        f"/web/pending?ledger_id={installed_web.shared_ledger_id}",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
        follow_redirects=False,
    )

    assert page.status_code == 200, page.text
    assert "共同账本" in page.text
    assert installed_web.installation_ledger_name in page.text
    assert "成员" in page.text
    assert 'action="/web/auth/ledgers"' in page.text
    assert 'name="ledger_id" value="owner"' in page.text
    assert 'name="ledger_id" value="shared_household"' in page.text
    assert 'href="/web/pending?ledger_id=owner' not in page.text
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == installed_web.shared_ledger_id)
            .where(LedgerMember.account_id == installed_web.installation_account_id)
        )
        assert membership is not None
        assert membership.role == "member"


def test_invalid_local_cookie_is_cleared_instead_of_falling_back_to_owner(
    installed_web: _InstalledWeb,
) -> None:
    response = installed_web.browser.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}=not-a-real-session"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/web/auth/local?")
    set_cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie


def test_live_web_identity_keeps_token_when_selected_membership_is_removed(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)

    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == installed_web.shared_ledger_id)
            .where(LedgerMember.account_id == installed_web.installation_account_id)
        )
        assert membership is not None
        membership.disabled_at = now_utc()
        db.commit()

    response = installed_web.browser.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/web/auth/ledgers?next=%2Fweb%2Fpending"
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
    with SessionLocal() as db:
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        assert token is not None
        assert token.revoked_at is None


def test_live_web_identity_without_any_membership_shows_recovery_message(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)
    with SessionLocal() as db:
        memberships = list(
            db.scalars(
                select(LedgerMember).where(
                    LedgerMember.account_id == installed_web.installation_account_id
                )
            )
        )
        assert memberships
        for membership in memberships:
            membership.disabled_at = now_utc()
        db.commit()

    picker = installed_web.browser.get(
        "/web/auth/ledgers?next=/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )

    assert picker.status_code == 409
    assert "当前账户没有可访问的账本" in picker.text


def test_identity_ledger_picker_switches_same_token_to_another_live_membership(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)
    with SessionLocal() as db:
        token_before = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        membership = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == installed_web.shared_ledger_id)
            .where(LedgerMember.account_id == installed_web.installation_account_id)
        )
        assert token_before is not None
        assert membership is not None
        device_id = token_before.device_id
        membership.disabled_at = now_utc()
        db.commit()

    picker = installed_web.browser.get(
        "/web/auth/ledgers?next=/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )

    assert picker.status_code == 200, picker.text
    assert "选择账本" in picker.text
    assert "安装账户" in picker.text
    assert installed_web.installation_ledger_name in picker.text
    assert "共同账本" not in picker.text
    assert 'action="/web/auth/ledgers"' in picker.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', picker.text)
    assert csrf is not None, picker.text
    csrf_seed = picker.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_seed is not None

    switched = installed_web.browser.post(
        "/web/auth/ledgers",
        data={
            "csrf_token": csrf.group(1),
            "ledger_id": "owner",
            "next": "/web/pending",
        },
        headers={
            "Cookie": (
                f"{CSRF_COOKIE_NAME}={csrf_seed}; "
                f"{SESSION_COOKIE_NAME}={session_token}"
            ),
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert switched.status_code == 303, switched.text
    assert switched.headers["location"] == "/web/pending"
    assert SESSION_COOKIE_NAME not in switched.headers.get("set-cookie", "")
    with SessionLocal() as db:
        token_after = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        assert token_after is not None
        assert token_after.account_id == installed_web.installation_account_id
        assert token_after.device_id == device_id
        assert token_after.ledger_id == "owner"

    page = installed_web.browser.get(
        "/web/pending?ledger_id=owner",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
        follow_redirects=False,
    )
    assert page.status_code == 200, page.text
