from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from app.database import SessionLocal, engine
from app.main import app
from app.middleware.web_session import DESKTOP_BRIDGE_HEADER, DESKTOP_BRIDGE_VERSION
from app.models import (
    Account,
    AuthToken,
    Device,
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
    InstallationOwnerClaim,
    LedgerMember,
)
from app.services.identity_service import (
    bootstrap_installation_owner,
    hash_secret,
    new_session_token,
)
from tests._infra.env import ADMIN_TEST_DATABASE_URL
from tests.desktop_activation_support import activate, pair_desktop

pytestmark = [pytest.mark.currency_binding_unbound, pytest.mark.real_db]


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
def adoption_browser() -> Iterator[_AdoptionBrowser]:
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


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html)
    assert match is not None, f"missing hidden field: {name}"
    return match.group(1)


def test_installation_owner_desktop_can_complete_currency_adoption(
    adoption_browser: _AdoptionBrowser,
) -> None:
    entry = adoption_browser.client.get(
        "/web/pending",
        headers=adoption_browser.headers,
        follow_redirects=False,
    )
    assert entry.status_code == 303
    assert entry.headers["location"] == "/web/currency-adoption"

    preview = adoption_browser.client.get(
        "/web/currency-adoption",
        headers=adoption_browser.headers,
    )

    assert preview.status_code == 200, preview.text
    assert "确认这台小票夹的本位币" in preview.text
    assert "不会换算或改写已有金额" in preview.text
    assert "确认后不能在这里更改" in preview.text
    assert not re.search(r"[0-9a-f]{64}", preview.text)

    response = adoption_browser.client.post(
        "/web/currency-adoption",
        headers=adoption_browser.headers,
        data={
            "csrf_token": _hidden_value(preview.text, "csrf_token"),
            "home_currency_code": "JPY",
            "currency_contract_version": _hidden_value(
                preview.text,
                "currency_contract_version",
            ),
            "expected_state": _hidden_value(preview.text, "expected_state"),
            "expected_binding_revision": _hidden_value(
                preview.text,
                "expected_binding_revision",
            ),
            "evidence_token": _hidden_value(preview.text, "evidence_token"),
            "idempotency_key": _hidden_value(preview.text, "idempotency_key"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/web/currency-adoption"
    completed = adoption_browser.client.get(
        response.headers["location"],
        headers=adoption_browser.headers,
    )
    assert completed.status_code == 200, completed.text
    assert "本位币已确认" in completed.text
    assert "日元" in completed.text
    assert "JPY" in completed.text

    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "ACTIVE"
        assert binding.home_currency_code == "JPY"
        assert binding.binding_revision == 1
        event = db.scalar(select(InstallationCurrencyAuditLog))
        claim = db.scalar(select(InstallationOwnerClaim))
        assert event is not None
        assert claim is not None
        assert event.action == "OWNER_ADOPTION"
        assert event.actor_account_public_id is not None
        owner = db.get(Account, claim.account_id)
        desktop = db.scalar(
            select(Device).where(Device.public_id == event.actor_device_public_id)
        )
        assert owner is not None
        assert desktop is not None
        assert event.actor_account_public_id == owner.public_id
        assert desktop.account_id == claim.account_id
        assert desktop.platform == "desktop"


def test_currency_adoption_has_one_authenticated_product_entry(
    adoption_browser: _AdoptionBrowser,
) -> None:
    wrong_token = new_session_token()
    with SessionLocal() as db:
        claim = db.scalar(select(InstallationOwnerClaim))
        assert claim is not None
        account = Account(display_name="家庭成员")
        db.add(account)
        db.flush()
        db.add(LedgerMember(ledger_id=claim.ledger_id, account_id=account.id, role="member"))
        device = Device(account_id=account.id, device_name="另一台电脑", platform="desktop")
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret(wrong_token),
                account_id=account.id,
                device_id=device.id,
                ledger_id=claim.ledger_id,
                scope="app",
            )
        )
        db.commit()

    naked = adoption_browser.client.get("/web/currency-adoption")
    wrong_account = adoption_browser.client.get(
        "/web/currency-adoption",
        headers={
            DESKTOP_BRIDGE_HEADER: DESKTOP_BRIDGE_VERSION,
            "Authorization": f"Bearer {wrong_token}",
        },
    )
    old_api = adoption_browser.client.get(
        "/api/maintenance/currency-binding/adoption",
    )

    assert naked.status_code == 403
    assert wrong_account.status_code == 403
    assert old_api.status_code == 404
