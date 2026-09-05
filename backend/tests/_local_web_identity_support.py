"""Shared installed-Web setup for local identity integration tests."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Account, InstallationOwnerClaim, Ledger, LedgerMember
from app.routes.web_auth import PAIRING_ATTEMPT_COOKIE_NAME, SESSION_COOKIE_NAME
from app.services.currency_binding_service import resolve_write_capability
from app.services.identity_service import bootstrap_installation_owner


@dataclass(frozen=True)
class _InstalledWeb:
    browser: TestClient
    installation_account_id: int
    installation_ledger_name: str
    shared_ledger_id: str


def installed_web_setup() -> Iterator[_InstalledWeb]:
    with SessionLocal() as db:
        bootstrap_installation_owner(
            db,
            operation_id="pytest-local-web-identity",
            installation_id="pytest-local-web-installation",
            bootstrap_secret="pytest-local-web-bootstrap-secret-32-bytes",
            account_name="安装账户",
            ledger_name="安装账户的账本",
            device_name="Windows 安装来源",
        )
        claim = db.scalar(select(InstallationOwnerClaim))
        assert claim is not None
        installation_ledger = db.scalar(
            select(Ledger).where(Ledger.ledger_id == claim.ledger_id)
        )
        assert installation_ledger is not None

        household_owner = Account(display_name="共同账本拥有者")
        db.add(household_owner)
        db.flush()
        shared = Ledger(
            ledger_id="shared_household",
            name="共同账本",
            owner_account_id=household_owner.id,
        )
        db.add(shared)
        db.flush()
        db.add_all(
            [
                LedgerMember(
                    ledger_id=shared.ledger_id,
                    account_id=household_owner.id,
                    role="owner",
                ),
                LedgerMember(
                    ledger_id=shared.ledger_id,
                    account_id=claim.account_id,
                    role="member",
                ),
            ]
        )
        resolve_write_capability(db)
        db.commit()
        installation_account_id = claim.account_id
        installation_ledger_name = installation_ledger.name

    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 51241),
    ) as browser:
        yield _InstalledWeb(
            browser=browser,
            installation_account_id=installation_account_id,
            installation_ledger_name=installation_ledger_name,
            shared_ledger_id="shared_household",
        )


def _local_confirmation(
    installed_web: _InstalledWeb,
    *,
    next_url: str = "/web/pending",
) -> tuple[object, str, str]:
    preview = installed_web.browser.get(f"/web/auth/local?next={next_url}")
    assert preview.status_code == 200, preview.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', preview.text)
    assert csrf is not None, preview.text
    attempt = preview.cookies.get(PAIRING_ATTEMPT_COOKIE_NAME)
    csrf_seed = preview.cookies.get(CSRF_COOKIE_NAME)
    assert attempt is not None
    assert csrf_seed is not None
    return preview, csrf.group(1), (
        f"{CSRF_COOKIE_NAME}={csrf_seed}; "
        f"{PAIRING_ATTEMPT_COOKIE_NAME}={attempt}"
    )


def _connect_local_session(
    installed_web: _InstalledWeb,
    *,
    ledger_id: str | None = None,
    next_url: str = "/web/pending",
) -> str:
    _, csrf_token, cookie_header = _local_confirmation(
        installed_web,
        next_url=next_url,
    )
    response = installed_web.browser.post(
        "/web/auth/local",
        data={
            "csrf_token": csrf_token,
            "ledger_id": ledger_id or installed_web.shared_ledger_id,
            "next": next_url,
        },
        headers={"Cookie": cookie_header, "Origin": "http://127.0.0.1:8000"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    token = response.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    return token


__all__ = [
    "_InstalledWeb",
    "_connect_local_session",
    "_local_confirmation",
    "installed_web_setup",
]
