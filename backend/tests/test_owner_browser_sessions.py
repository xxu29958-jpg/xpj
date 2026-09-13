"""Owner inventory distinguishes browser session history from connected devices."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import AuthToken, Device
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from app.services.owner_console_service import get_index_vm
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


def _logout(installed_web: _InstalledWeb, token: str) -> None:
    page = installed_web.browser.get(
        "/web/pending", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"}
    )
    assert page.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf is not None
    response = installed_web.browser.post(
        "/web/auth/logout",
        data={"csrf_token": csrf.group(1)},
        headers={
            "Cookie": (
                f"{SESSION_COOKIE_NAME}={token}; "
                f"{CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}"
            ),
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.parametrize("end_session", ["expire", "logout"])
def test_reconnect_keeps_ended_browser_out_of_connected_inventory(
    installed_web: _InstalledWeb, end_session: str,
) -> None:
    first = _connect_local_session(installed_web)
    with SessionLocal() as db:
        first_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(first)))
        assert first_row is not None
        first_device_id = first_row.device_id
        first_device = db.get(Device, first_device_id)
        assert first_device is not None
        first_public_id = first_device.public_id
        baseline_count = get_index_vm(db).active_device_count

    # Another browser stays connected when the first one ends its session.
    installed_web.browser.cookies.clear()
    other = _connect_local_session(installed_web)
    if end_session == "logout":
        _logout(installed_web, first)
    else:
        with SessionLocal() as db:
            first_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(first)))
            assert first_row is not None
            first_row.expires_at = now_utc() - timedelta(seconds=1)
            db.commit()

    with SessionLocal() as db:
        assert get_index_vm(db).active_device_count == baseline_count
        first_device = db.get(Device, first_device_id)
        assert first_device is not None
        assert first_device.revoked_at is None

    installed_web.browser.cookies.clear()
    replacement = _connect_local_session(installed_web)
    page = installed_web.browser.get("/owner/devices")
    assert page.status_code == 200
    history = re.search(r'<details\b[^>]*id="browser-session-history"[^>]*>(.*?)</details>', page.text, re.S)
    assert history is not None
    assert " open" not in history.group(0).split(">", 1)[0]
    assert first_public_id in history.group(1)
    assert "会话已结束" in history.group(1)
    with SessionLocal() as db:
        assert get_index_vm(db).active_device_count == baseline_count + 1
        for token in (other, replacement):
            row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
            assert row is not None
            device = db.get(Device, row.device_id)
            assert device is not None
            assert device.public_id in page.text
            assert device.public_id not in history.group(1)
            assert row.revoked_at is None
            assert device.revoked_at is None
        first_row = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(first)))
        assert first_row is not None
        assert (first_row.revoked_at is not None) == (end_session == "logout")
