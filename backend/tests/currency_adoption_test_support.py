"""Shared preparation for the existing currency adoption consumers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.database import SessionLocal, engine
from app.main import app
from app.middleware.web_session import DESKTOP_BRIDGE_HEADER, DESKTOP_BRIDGE_VERSION
from app.services.identity_service import (
    bootstrap_installation_owner,
)
from tests._infra.env import ADMIN_TEST_DATABASE_URL
from tests.desktop_activation_support import activate, pair_desktop


@dataclass(frozen=True)
class _AdoptionBrowser:
    client: TestClient
    headers: dict[str, str]


def _force_adoption_required() -> None:
    """Model the one state that only the legacy-data migration can create."""
    admin_engine = create_engine(
        make_url(ADMIN_TEST_DATABASE_URL).set(
            database=engine.url.database,
        )
    )
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE installation_currency_bindings "
                    "DISABLE TRIGGER trg_currency_binding_update_delete"
                )
            )
            connection.execute(
                text(
                    "UPDATE installation_currency_bindings "
                    "SET state = 'ADOPTION_REQUIRED', "
                    "home_currency_code = NULL, minor_unit_exponent = NULL, "
                    "rounding_mode = NULL, binding_revision = 0, "
                    "provenance = NULL, evidence_sha256 = NULL, activated_at = NULL "
                    "WHERE singleton_id = 1"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE installation_currency_bindings "
                    "ENABLE TRIGGER trg_currency_binding_update_delete"
                )
            )
    finally:
        admin_engine.dispose()


@pytest.fixture()
def adoption_browser(request: pytest.FixtureRequest) -> Iterator[_AdoptionBrowser]:
    with SessionLocal() as db:
        bootstrap = bootstrap_installation_owner(
            db,
            operation_id="pytest-currency-adoption",
            installation_id="pytest-installation",
            bootstrap_secret="pytest-currency-adoption-secret-32-bytes",
            account_name="安装拥有者",
            ledger_name="家庭账本",
            device_name="Windows 后端",
        )
        db.commit()
    if getattr(request, "param", "ADOPTION_REQUIRED") != "EMPTY":
        _force_adoption_required()

    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 51201),
    ) as browser:
        payload, _ = pair_desktop(browser, bootstrap.pairing_code)
        activated = activate(browser, payload)
        assert activated.status_code == 200, activated.text
        token = activated.json()["session_token"]
        yield _AdoptionBrowser(
            client=browser,
            headers={
                DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION,
                "Authorization": f"Bearer {token}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
