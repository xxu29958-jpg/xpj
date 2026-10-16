"""Real HTTP setup shared by the Web debt command consumers."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Debt
from tests._infra.currency import activate_test_currency_authority
from tests._local_web_identity_support import _InstalledWeb
from tests._runtime_protocol import negotiated_headers


def _headers(identity) -> dict[str, str]:
    return {**identity.app_headers, "Idempotency-Key": str(uuid4())}


def _create_debt(
    web_client: TestClient,
    *,
    identity,
    principal_amount_cents: int = 50_000,
) -> dict:
    response = web_client.post(
        "/api/debts",
        headers=negotiated_headers(web_client, _headers(identity)),
        json={
            "home_currency_code": "CNY", "direction": "i_owe",
            "counterparty_type": "external",
            "counterparty_label": "测试信用卡",
            "principal_amount_cents": principal_amount_cents,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _form(
    debt: dict,
    *,
    idempotency_key: str,
    **values: str,
) -> dict[str, str]:
    return {
        "csrf_token": "test-client-bypasses-middleware-check",
        "ledger_id": "owner",
        "expected_row_version": str(debt["row_version"]),
        "idempotency_key": idempotency_key,
        **values,
    }


def _detail(web_client: TestClient, *, identity, public_id: str) -> dict:
    response = web_client.get(
        f"/api/debts/{public_id}",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_external_debt(installed_web: _InstalledWeb) -> str:
    with SessionLocal() as db:
        activate_test_currency_authority(db, "CNY")
        debt = Debt(
            tenant_id=installed_web.shared_ledger_id,
            owner_account_id=installed_web.installation_account_id,
            created_by_account_id=installed_web.installation_account_id,
            direction="i_owe",
            counterparty_type="external",
            counterparty_label="原还款绑定核对",
            principal_amount_cents=50_000,
            home_currency_code="CNY",
            source_type="manual",
        )
        db.add(debt)
        db.commit()
        return debt.public_id
