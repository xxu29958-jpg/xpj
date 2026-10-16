"""A real installed browser retains a refused repayment and acknowledges only its original fact."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Debt, Repayment
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._local_web_identity_support import (
    _connect_local_session,
    _installed_scope,
    _InstalledWeb,
    installed_web_setup,
)
from tests._web_debt_command_support import _seed_external_debt
from tests._web_native_form_support import _NativeForm, open_repayment_task

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


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
    page = open_repayment_task(installed_web.browser, page, headers=headers)
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
            assert fact.paid_at is None
            assert fact.accounting_time_snapshot["precision"] == "date_only"
            assert fact.accounting_time_snapshot["instant_utc"] is None
            assert fact.accounting_time_snapshot["user_local_date"] == original["paid_at"]
            assert fact.accounting_time_snapshot["calendar_revision"] == int(original["calendar_revision"])
            assert ack["repaymentPublicId"] == fact.public_id
            assert repayment_id is None or repayment_id == fact.public_id
            repayment_id = fact.public_id
