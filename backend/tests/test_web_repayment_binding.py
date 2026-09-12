"""A real installed browser retains a refused repayment and acknowledges only its original fact."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from datetime import datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Account, AuthToken, Debt, Device, Repayment
from app.models.dataset_authority import DatasetAuthorityRecord
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.identity_service import hash_secret
from tests._infra.currency import activate_test_currency_authority
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    installed_web_setup,
)
from tests.test_web_correction_fx_continuation import _NativeForm

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


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


def _installed_scope(installed_web: _InstalledWeb, session_token: str) -> dict[str, str]:
    with SessionLocal() as db:
        authority = db.get(DatasetAuthorityRecord, 1)
        token = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token)))
        assert authority is not None and token is not None
        device = db.get(Device, token.device_id)
        assert device is not None and device.platform == "web"
        account = db.get(Account, device.account_id)
        assert account is not None and account.id == installed_web.installation_account_id
        return {
            "datasetId": authority.dataset_id,
            "clientGeneration": authority.client_generation,
            "accountId": account.public_id,
            "ledgerId": installed_web.shared_ledger_id,
            "deviceId": device.public_id,
        }


def test_installed_native_repayment_rejects_every_stale_binding_axis_then_replays_one_fact(installed_web):
    public_id = _seed_external_debt(installed_web)
    detail_url = f"/web/debts/{public_id}?ledger_id={installed_web.shared_ledger_id}"
    action = f"/web/debts/{public_id}/repayments"
    session_token = _connect_local_session(installed_web, next_url=detail_url)
    session_cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    page = installed_web.browser.get(detail_url, headers={"Cookie": session_cookie})
    assert page.status_code == 200, page.text
    csrf_seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_seed is not None
    headers = {
        "Cookie": f"{session_cookie}; {CSRF_COOKIE_NAME}={csrf_seed}",
        "Origin": "http://127.0.0.1:8000",
    }
    form = _NativeForm(page.text, action)
    form.set("amount_major", "23.45")
    form.set("paid_at", "2026-09-01")
    original = {name: form.one(name) for name in form.fields}
    scope = _installed_scope(installed_web, session_token)
    assert json.loads(original["origin_binding"]) == scope
    assert original["debt_public_id"] == public_id
    assert original["ledger_id"] == scope["ledgerId"]
    assert original["home_currency_code"] == "CNY"
    assert original["idempotency_key"] and original["paid_at_timezone"]

    stale_origins = {"legacy_unbound": ""}
    stale_origins.update({axis: json.dumps({**scope, axis: str(uuid4())}) for axis in scope})
    for axis, stale_origin in stale_origins.items():
        attempted = {**original, "origin_binding": stale_origin}
        refused = installed_web.browser.post(action, data=attempted, headers=headers, follow_redirects=False)
        assert refused.status_code == 409, (axis, refused.text)
        assert 'data-repayment-result="blocked"' in refused.text
        assert "data-repayment-ack=" not in refused.text
        retained = _NativeForm(refused.text, action)
        for name, value in attempted.items():
            if name != "csrf_token":
                assert retained.one(name) == value, (axis, name)
        with SessionLocal() as db:
            assert list(db.scalars(select(Repayment))) == [], axis
            debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
            assert debt is not None
            assert debt.row_version == int(original["expected_row_version"]), axis

    # The original native request stays usable; submitting it again is the same
    # command, not permission to create a replacement at the new Debt version.
    repayment_id = None
    for _ in range(2):
        accepted = installed_web.browser.post(action, data=original, headers=headers, follow_redirects=False)
        assert accepted.status_code == 200, accepted.text
        marker = re.search(r'data-repayment-ack="([^"]+)"', accepted.text)
        assert marker is not None, accepted.text
        ack = json.loads(html.unescape(marker[1]))
        assert ack["scope"] == scope
        assert ack["clientRef"] == original["idempotency_key"]
        assert ack["values"] == {name: value for name, value in original.items()
                                 if name not in {"csrf_token", "idempotency_key"}}
        with SessionLocal() as db:
            facts = list(db.scalars(select(Repayment)))
            assert len(facts) == 1
            fact = facts[0]
            debt = db.scalar(select(Debt).where(Debt.public_id == public_id))
            assert debt is not None and fact.debt_id == debt.id
            assert debt.row_version == int(original["expected_row_version"]) + 1
            assert fact.amount_cents == 2345
            assert fact.actor_account_id == installed_web.installation_account_id
            assert fact.idempotency_key == original["idempotency_key"]
            assert fact.paid_at == datetime.combine(
                datetime.fromisoformat(original["paid_at"]).date(), time.min,
                tzinfo=ZoneInfo(original["paid_at_timezone"]),
            )
            assert ack["repaymentPublicId"] == fact.public_id
            assert repayment_id is None or repayment_id == fact.public_id
            repayment_id = fact.public_id
