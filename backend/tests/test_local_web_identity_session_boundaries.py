"""Installed loopback browser-session boundary regressions."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Account, AuthToken, Device
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret, new_session_token
from app.services.session_lifecycle_service import WEB_SESSION_TTL_SECONDS
from app.services.time_service import now_utc
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    installed_web_setup,
)

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


def test_installed_loopback_rejects_valid_web_cookie_for_another_account(
    installed_web: _InstalledWeb,
) -> None:
    unrelated_token = new_session_token()
    with SessionLocal() as db:
        unrelated_account = db.scalar(
            select(Account).where(Account.display_name == "共同账本拥有者")
        )
        assert unrelated_account is not None
        unrelated_device = Device(
            account_id=unrelated_account.id,
            device_name="另一账户的浏览器",
            platform="web",
        )
        db.add(unrelated_device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(unrelated_token),
                account_id=unrelated_account.id,
                device_id=unrelated_device.id,
                ledger_id=installed_web.shared_ledger_id,
                scope="app",
                expires_at=now_utc() + timedelta(seconds=WEB_SESSION_TTL_SECONDS),
            )
        )
        db.commit()

    response = installed_web.browser.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={unrelated_token}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/web/auth/local?")
    set_cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "Max-Age=0" in set_cookie


def test_installed_loopback_logout_returns_to_local_confirmation(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)
    page = installed_web.browser.get(
        "/web/pending",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    assert page.status_code == 200, page.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    csrf_seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert csrf is not None
    assert csrf_seed is not None

    response = installed_web.browser.post(
        "/web/auth/logout",
        data={"csrf_token": csrf.group(1)},
        headers={
            "Cookie": (
                f"{SESSION_COOKIE_NAME}={session_token}; "
                f"{CSRF_COOKIE_NAME}={csrf_seed}"
            ),
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/web/auth/local"
