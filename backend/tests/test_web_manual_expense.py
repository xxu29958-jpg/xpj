"""Native Web manual-expense entry uses the existing expense command owner."""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import AuthToken, Device, Expense, ExpenseRevision, LedgerMember
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.routes.web_expense_create import _manual_expense_payload
from app.services.identity_service import hash_secret
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    installed_web_setup,
)

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


def _assert_confirmed_manual_fact(
    installed_web: _InstalledWeb,
    *,
    session_token: str,
    client_ref: str,
    location: str,
) -> None:
    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense).where(
                Expense.tenant_id == installed_web.shared_ledger_id,
                Expense.source == "手动记账",
            )
        )
        assert expense is not None
        assert db.scalar(
            select(func.count()).select_from(Expense).where(
                Expense.tenant_id == installed_web.shared_ledger_id,
                Expense.source == "手动记账",
            )
        ) == 1
        assert (expense.amount_cents, expense.status) == (2345, "confirmed")
        assert (expense.merchant, expense.note) == ("社区超市", "周末午餐")
        assert location == (
            f"/web/expenses/{expense.id}/edit?"
            "ledger_id=shared_household&return_to=confirmed"
        )
        token = db.scalar(
            select(AuthToken).where(AuthToken.token_hash == hash_secret(session_token))
        )
        assert token is not None
        device = db.get(Device, token.device_id)
        revision = db.scalar(
            select(ExpenseRevision).where(ExpenseRevision.expense_id == expense.id)
        )
        assert device is not None
        assert expense.draft_idempotency_key == f"{device.id}:{client_ref}"
        assert revision is not None
        assert revision.actor_account_id == installed_web.installation_account_id
        assert revision.actor_device_public_id == device.public_id


def test_member_can_open_native_manual_expense_form(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(
        installed_web,
        next_url="/web/expenses/new",
    )

    response = installed_web.browser.get(
        "/web/expenses/new",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
        follow_redirects=False,
    )

    assert response.status_code == 200, response.text
    assert 'data-domain="transactions"' in response.text
    assert "手动记一笔" in response.text
    assert 'action="/web/expenses/new"' in response.text
    assert 'name="ledger_id" value="shared_household"' in response.text
    assert re.search(
        r'name="client_ref" value="[0-9a-f]{32}"',
        response.text,
    )
    assert 'name="csrf_token"' in response.text
    assert 'name="currency_code"' in response.text
    assert ">CNY</option>" in response.text
    assert 'href="/web/expenses/new"' in response.text
    assert 'data-shell-shortcut="manual-expense"' in response.text
    assert 'aria-keyshortcuts="N"' in response.text


def test_manual_expense_replay_uses_web_device_and_creates_one_confirmed_fact(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(
        installed_web,
        next_url="/web/expenses/new",
    )
    session_cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    page = installed_web.browser.get(
        "/web/expenses/new",
        headers={"Cookie": session_cookie},
    )
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    client_ref = re.search(r'name="client_ref" value="([^"]+)"', page.text)
    csrf_seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert csrf is not None
    assert client_ref is not None
    assert csrf_seed is not None
    form = {
        "csrf_token": csrf.group(1),
        "ledger_id": installed_web.shared_ledger_id,
        "client_ref": client_ref.group(1),
        "amount_major": "23.45",
        "currency_code": "CNY",
        "merchant": "社区超市",
        "category": "餐饮",
        "spent_at": "2026-09-05T12:34",
        "note": "周末午餐",
    }
    headers = {
        "Cookie": f"{session_cookie}; {CSRF_COOKIE_NAME}={csrf_seed}",
        "Origin": "http://127.0.0.1:8000",
    }

    first = installed_web.browser.post(
        "/web/expenses/new",
        data=form,
        headers=headers,
        follow_redirects=False,
    )
    replay = installed_web.browser.post(
        "/web/expenses/new",
        data=form,
        headers=headers,
        follow_redirects=False,
    )

    assert first.status_code == 303, first.text
    assert replay.status_code == 303, replay.text
    assert replay.headers["location"] == first.headers["location"]
    _assert_confirmed_manual_fact(
        installed_web,
        session_token=session_token,
        client_ref=client_ref.group(1),
        location=first.headers["location"],
    )


def test_form_money_maps_to_the_existing_manual_expense_payload() -> None:
    common = {
        "merchant": "商家",
        "category": "餐饮",
        "note": "备注",
        "spent_at": "2026-09-05T12:34",
        "client_ref": "a" * 32,
        "home_currency": "CNY",
    }

    home = _manual_expense_payload(
        amount_major="23.45",
        currency_code="CNY",
        **common,
    )
    foreign = _manual_expense_payload(
        amount_major="23.45",
        currency_code="USD",
        **common,
    )

    assert home.amount_cents == 2345
    assert home.original_currency is None
    assert foreign.amount_cents is None
    assert foreign.original_currency == "USD"
    assert foreign.original_amount == Decimal("23.45")


def test_missing_fx_keeps_same_created_expense_in_pending_recovery(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(
        installed_web,
        next_url="/web/expenses/new",
    )
    session_cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    page = installed_web.browser.get(
        "/web/expenses/new",
        headers={"Cookie": session_cookie},
    )
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    client_ref = re.search(r'name="client_ref" value="([^"]+)"', page.text)
    csrf_seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert csrf is not None
    assert client_ref is not None
    assert csrf_seed is not None

    created = installed_web.browser.post(
        "/web/expenses/new",
        data={
            "csrf_token": csrf.group(1),
            "ledger_id": installed_web.shared_ledger_id,
            "client_ref": client_ref.group(1),
            "amount_major": "123.45",
            "currency_code": "USD",
            "merchant": "Pending FX Cafe",
            "category": "餐饮",
            "spent_at": "2026-05-04T10:00",
            "note": "保留原币金额",
        },
        headers={
            "Cookie": f"{session_cookie}; {CSRF_COOKIE_NAME}={csrf_seed}",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303, created.text
    with SessionLocal() as db:
        expense = db.scalar(
            select(Expense).where(
                Expense.tenant_id == installed_web.shared_ledger_id,
                Expense.source == "手动记账",
            )
        )
        assert expense is not None
        assert expense.status == "pending"
        assert expense.fx_status == "pending"
        assert expense.amount_cents is None
        assert expense.original_currency_code == "USD"
        assert expense.original_amount_minor == 12345
        assert db.scalar(
            select(func.count())
            .select_from(ExpenseRevision)
            .where(ExpenseRevision.expense_id == expense.id)
        ) == 0
        expected_location = (
            f"/web/expenses/{expense.id}/edit?"
            "ledger_id=shared_household&return_to=pending"
        )
    assert created.headers["location"] == expected_location

    recovery = installed_web.browser.get(
        expected_location,
        headers={"Cookie": session_cookie},
    )
    assert recovery.status_code == 200, recovery.text
    assert 'name="manual_exchange_rate"' in recovery.text
    assert "仅用于本笔账单" in recovery.text


def test_viewer_neither_sees_nor_opens_manual_expense_entry(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)
    session_cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    with SessionLocal() as db:
        membership = db.scalar(
            select(LedgerMember).where(
                LedgerMember.ledger_id == installed_web.shared_ledger_id,
                LedgerMember.account_id == installed_web.installation_account_id,
            )
        )
        assert membership is not None
        membership.role = "viewer"
        db.commit()

    confirmed = installed_web.browser.get(
        "/web/confirmed",
        headers={"Cookie": session_cookie},
    )
    direct = installed_web.browser.get(
        "/web/expenses/new",
        headers={"Cookie": session_cookie},
        follow_redirects=False,
    )

    assert confirmed.status_code == 200, confirmed.text
    assert 'href="/web/expenses/new"' not in confirmed.text
    assert 'data-shell-shortcut="manual-expense"' not in confirmed.text
    assert direct.status_code == 403, direct.text
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Expense).where(
                Expense.tenant_id == installed_web.shared_ledger_id,
                Expense.source == "手动记账",
            )
        ) == 0


def test_invalid_amount_preserves_draft_and_same_create_intent(
    installed_web: _InstalledWeb,
) -> None:
    session_token = _connect_local_session(installed_web)
    session_cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    page = installed_web.browser.get(
        "/web/expenses/new",
        headers={"Cookie": session_cookie},
    )
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    client_ref = re.search(r'name="client_ref" value="([^"]+)"', page.text)
    csrf_seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert csrf is not None
    assert client_ref is not None
    assert csrf_seed is not None

    refused = installed_web.browser.post(
        "/web/expenses/new",
        data={
            "csrf_token": csrf.group(1),
            "ledger_id": installed_web.shared_ledger_id,
            "client_ref": client_ref.group(1),
            "amount_major": "not-money",
            "currency_code": "CNY",
            "merchant": "草稿商家",
            "category": "日用",
            "spent_at": "2026-09-05T12:34",
            "note": "这段不能丢",
        },
        headers={
            "Cookie": f"{session_cookie}; {CSRF_COOKIE_NAME}={csrf_seed}",
            "Origin": "http://127.0.0.1:8000",
        },
        follow_redirects=False,
    )

    assert refused.status_code == 422, refused.text
    assert "草稿商家" in refused.text
    assert "这段不能丢" in refused.text
    assert re.search(
        rf'name="client_ref" value="{client_ref.group(1)}"',
        refused.text,
    )
    assert re.search(
        r'name="amount_major"[^>]*value="not-money"',
        refused.text,
    )
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Expense).where(
                Expense.tenant_id == installed_web.shared_ledger_id,
                Expense.source == "手动记账",
            )
        ) == 0


@pytest.mark.parametrize("change", ["ledger", "permission", "device"])
def test_open_manual_form_cannot_write_after_its_binding_changes(
    installed_web: _InstalledWeb, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    from app.routes import web_expense_create

    session_token = _connect_local_session(installed_web)
    cookie = f"{SESSION_COOKIE_NAME}={session_token}"
    page = installed_web.browser.get("/web/expenses/new", headers={"Cookie": cookie})
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    client_ref = re.search(r'name="client_ref" value="([^"]+)"', page.text)
    assert csrf is not None
    assert client_ref is not None
    headers = {
        "Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000",
    }
    if change == "ledger":
        switched = installed_web.browser.post(
            "/web/auth/ledgers",
            data={"csrf_token": csrf.group(1), "ledger_id": "owner"},
            headers=headers,
            follow_redirects=False,
        )
        assert switched.status_code == 303
    elif change == "device":
        installed_web.browser.cookies.clear()
        replacement = _connect_local_session(installed_web)
        headers["Cookie"] = (
            f"{SESSION_COOKIE_NAME}={replacement}; "
            f"{CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}"
        )
    else:
        parse = web_expense_create._manual_expense_payload

        def revoke_after_route_admission(**kwargs):
            with SessionLocal() as db:
                membership = db.scalar(select(LedgerMember).where(
                    LedgerMember.ledger_id == installed_web.shared_ledger_id,
                    LedgerMember.account_id == installed_web.installation_account_id,
                ))
                assert membership is not None
                membership.role = "viewer"
                db.commit()
            return parse(**kwargs)

        monkeypatch.setattr(web_expense_create, "_manual_expense_payload", revoke_after_route_admission)

    response = installed_web.browser.post(
        "/web/expenses/new",
        data={
            "csrf_token": csrf.group(1),
            "ledger_id": installed_web.shared_ledger_id,
            "client_ref": client_ref.group(1),
            "amount_major": "23.45",
            "currency_code": "CNY",
            "merchant": "旧表单的商家",
            "category": "餐饮",
            "spent_at": "2026-09-05T12:34",
        },
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == (403 if change == "permission" else 409), response.text
    assert "旧表单的商家" in response.text
    assert f'name="client_ref" value="{client_ref.group(1)}"' in response.text
    assert 'name="ledger_id" value="shared_household"' in response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
