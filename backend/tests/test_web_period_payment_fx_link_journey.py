"""Record-this-period payment stays a raw Expense until an explicit occurrence link."""

from __future__ import annotations

import re
from collections.abc import Iterator
from html import unescape
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.middleware.csrf import CSRF_COOKIE_NAME
from app.models import Expense
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.income_plan_service import create_income_plan
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    installed_web_setup,
)
from tests._runtime_protocol import current_protocol_headers
from tests.test_web_recurring_occurrences import _form, _record_payment_href

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]

_SERIES_PERIOD = "2026-08"
_PAYMENT_MONTH = "2026-09"


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


def _hidden_fields(html: str) -> dict[str, str]:
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', html))


def _headers(session_token: str, page) -> dict[str, str]:
    seed = page.cookies.get(CSRF_COOKIE_NAME)
    assert seed is not None
    return {
        "Cookie": f"{SESSION_COOKIE_NAME}={session_token}; {CSRF_COOKIE_NAME}={seed}",
        "Origin": "http://127.0.0.1:8000",
    }


def _api_headers(session_token: str) -> dict[str, str]:
    return current_protocol_headers({"Authorization": f"Bearer {session_token}"})


def test_illegal_recurring_currency_opens_manual_choice_without_guessing_home(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.routes._web_expense_return_context import ExpenseReturnContext
    from app.routes.web_expense_create import _recurring_commitment_values

    item = SimpleNamespace(merchant_name="旧订阅", home_currency_code="ZZZ", baseline_amount_cents=2000)
    monkeypatch.setattr("app.routes.web_expense_create.get_recurring_item", lambda *args, **kwargs: item)
    values = _recurring_commitment_values(
        object(),
        "owner",
        ExpenseReturnContext(return_to="recurring_occurrence", return_recurring_public_id="series-1"),
    )
    assert values == {"merchant": "旧订阅", "currency_unspecified": "1"}


def test_unknown_recurring_currency_requires_explicit_choice_then_posts_pending(
    installed_web: _InstalledWeb,
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from app.routes import web_expense_create as create_route
    from app.services.recurring_service import get_recurring_item as real_get_recurring_item

    browser = installed_web.browser
    ledger_id = installed_web.shared_ledger_id
    session_token = _connect_local_session(installed_web)
    api = _api_headers(session_token)
    series = browser.post(
        "/api/recurring/items",
        headers={**api, "Idempotency-Key": str(uuid4())},
        json={
            "home_currency_code": "USD",
            "merchant": "旧订阅",
            "baseline_amount_cents": 2000,
            "next_expected_date": "2026-08-15",
        },
    )
    assert series.status_code == 201, series.text
    series_id = series.json()["public_id"]

    def unknown_item(db, tenant_id, public_id):
        item = real_get_recurring_item(db, tenant_id=tenant_id, public_id=public_id)
        return SimpleNamespace(
            merchant_name=item.merchant_name,
            home_currency_code=None,
            baseline_amount_cents=item.baseline_amount_cents,
        )

    monkeypatch.setattr(create_route, "get_recurring_item", unknown_item)
    href = (
        f"/web/expenses/new?ledger_id={ledger_id}"
        f"&return_to=recurring_occurrence&return_recurring_public_id={series_id}"
        f"&return_month={_SERIES_PERIOD}"
    )
    new_page = browser.get(href, headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"})
    assert new_page.status_code == 200, new_page.text
    assert 'value="旧订阅"' in new_page.text
    assert "原币种待核对" in new_page.text
    assert re.search(r'<option value="" selected>', new_page.text)
    assert not re.search(r'<option value="CNY" selected>', new_page.text)
    assert not re.search(r'name="amount_major"[^>]*value="20.00"', new_page.text)

    hidden = _hidden_fields(new_page.text)
    refused = browser.post(
        "/web/expenses/new",
        data={
            **hidden,
            "amount_major": "20.00",
            "currency_code": "",
            "merchant": "旧订阅",
            "category": "订阅",
            "spent_at": "2026-09-03T10:00",
        },
        headers=_headers(session_token, new_page),
        follow_redirects=False,
    )
    assert refused.status_code == 422, refused.text
    assert "原币种待核对" in refused.text

    created = browser.post(
        "/web/expenses/new",
        data={
            **hidden,
            "amount_major": "20.00",
            "currency_code": "USD",
            "merchant": "旧订阅",
            "category": "订阅",
            "spent_at": "2026-09-03T10:00",
        },
        headers=_headers(session_token, new_page),
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    created_id = int(urlsplit(created.headers["location"]).path.split("/")[3])
    detail = browser.get(f"/api/expenses/{created_id}", headers=api)
    assert detail.status_code == 200, detail.text
    expense = detail.json()
    assert expense["status"] == "pending"
    assert expense["original_currency_code"] == "USD"
    assert expense["home_currency"] == "CNY"


def test_period_payment_fx_confirm_return_then_explicit_link_zeros_reserve_once(
    installed_web: _InstalledWeb,
) -> None:
    browser = installed_web.browser
    ledger_id = installed_web.shared_ledger_id
    session_token = _connect_local_session(installed_web)
    api = _api_headers(session_token)
    with SessionLocal() as db:
        create_income_plan(
            db, home_currency_code="CNY", tenant_id=ledger_id, label="计划工资",
            source_type="salary", amount_cents=100_000, pay_day=1, frequency="one_time",
            income_month="2026-09",
        )
        db.commit()

    series = browser.post(
        "/api/recurring/items",
        headers={**api, "Idempotency-Key": str(uuid4())},
        json={
            "home_currency_code": "USD",
            "merchant": "海外订阅",
            "baseline_amount_cents": 2000,
            "next_expected_date": "2026-08-15",
        },
    )
    assert series.status_code == 201, series.text
    series_id = series.json()["public_id"]
    occurrence_path = f"/web/recurring/{series_id}/occurrence"

    unpaid = browser.get(
        occurrence_path,
        params={"ledger_id": ledger_id, "month": _SERIES_PERIOD},
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    assert unpaid.status_code == 200, unpaid.text
    href = _record_payment_href(
        unpaid.text, series_id=series_id, period=_SERIES_PERIOD, ledger_id=ledger_id,
    )
    parsed = urlsplit(unescape(href))
    assert parse_qs(parsed.query).get("ledger_id") == [ledger_id]

    new_page = browser.get(href, headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"})
    assert new_page.status_code == 200, new_page.text
    assert 'value="海外订阅"' in new_page.text
    assert re.search(r'name="amount_major"[^>]*value="20.00"', new_page.text)
    assert re.search(r'<option value="USD" selected>', new_page.text)
    create_form = {
        **_hidden_fields(new_page.text),
        "amount_major": "20.00",
        "currency_code": "USD",
        "merchant": "海外订阅",
        "category": "订阅",
        "spent_at": "2026-09-03T10:00",
        "note": "八月义务的九月付款",
    }
    created = browser.post(
        "/web/expenses/new",
        data=create_form,
        headers=_headers(session_token, new_page),
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    create_target = urlsplit(created.headers["location"])
    assert create_target.path.startswith("/web/expenses/")
    assert parse_qs(create_target.query).get("return_to") == ["recurring_occurrence"]
    assert parse_qs(create_target.query).get("return_recurring_public_id") == [series_id]
    assert parse_qs(create_target.query).get("return_month") == [_SERIES_PERIOD]
    created_id = int(create_target.path.split("/")[3])
    assert parse_qs(create_target.query).get("return_payment_expense_id") == [str(created_id)]
    detail = browser.get(f"/api/expenses/{created_id}", headers=api)
    assert detail.status_code == 200, detail.text
    expense = detail.json()
    assert expense["status"] == "pending"
    assert expense["fx_status"] == "pending"
    assert expense["original_currency_code"] == "USD"
    assert expense["home_currency"] == "CNY"

    before_confirm = browser.get(
        f"/api/recurring/items/{series_id}/occurrences/{_SERIES_PERIOD}",
        headers=api,
    )
    assert before_confirm.json()["state"] == "unfulfilled"
    assert before_confirm.json()["reserved_amount_cents"] == 2000
    assert before_confirm.json()["expense_public_id"] is None

    edit = browser.get(created.headers["location"], headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"})
    assert edit.status_code == 200, edit.text
    assert 'name="manual_exchange_rate"' in edit.text
    saved = browser.post(
        f"/web/expenses/{created_id}/save",
        data={
            **_hidden_fields(edit.text),
            "original_currency": "USD",
            "amount_yuan": "20.00",
            "manual_exchange_rate": "7",
            "merchant": "海外订阅",
            "category": "订阅",
            "note": "八月义务的九月付款",
            "tags": "",
            "expense_time": "2026-09-03T10:00",
        },
        headers=_headers(session_token, edit),
        follow_redirects=False,
    )
    assert saved.status_code == 303, saved.text
    reviewed = browser.get(f"/api/expenses/{created_id}", headers=api).json()
    assert reviewed["status"] == "pending"
    assert reviewed["fx_status"] == "ready"
    assert reviewed["amount_cents"] == 14000

    review_page = browser.get(saved.headers["location"], headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"})
    confirmed = browser.post(
        f"/web/expenses/{created_id}/confirm",
        data={
            **_hidden_fields(review_page.text),
            "original_currency": "USD",
            "amount_yuan": "20.00",
            "manual_exchange_rate": "7",
            "merchant": "海外订阅",
            "category": "订阅",
            "note": "八月义务的九月付款",
            "tags": "",
            "expense_time": "2026-09-03T10:00",
            "save_before_confirm": "1",
        },
        headers=_headers(session_token, review_page),
        follow_redirects=False,
    )
    assert confirmed.status_code == 303, confirmed.text
    confirm_target = urlsplit(confirmed.headers["location"])
    assert confirm_target.path == occurrence_path
    assert parse_qs(confirm_target.query) == {
        "ledger_id": [ledger_id], "month": [_SERIES_PERIOD], "payment_id": [str(created_id)],
    }
    focused_page = browser.get(
        confirmed.headers["location"],
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    assert focused_page.status_code == 200, focused_page.text
    assert "刚记录的付款" in focused_page.text
    assert f"/web/expenses/{created_id}/edit" in focused_page.text

    after_confirm = browser.get(
        f"/api/recurring/items/{series_id}/occurrences/{_SERIES_PERIOD}",
        headers=api,
    ).json()
    assert after_confirm["state"] == "unfulfilled"
    assert after_confirm["reserved_amount_cents"] == 2000
    assert after_confirm["expense_public_id"] is None
    fact = browser.get(f"/api/expenses/{created_id}", headers=api).json()
    assert fact["status"] == "confirmed"
    assert fact["original_currency_code"] == "USD"
    assert fact["home_currency"] == "CNY"

    replay = browser.post(
        "/web/expenses/new",
        data=create_form,
        headers=_headers(session_token, new_page),
        follow_redirects=False,
    )
    assert replay.status_code in {303, 409}, replay.text

    picker = browser.get(
        occurrence_path,
        params={"ledger_id": ledger_id, "month": _SERIES_PERIOD, "payment_month": _PAYMENT_MONTH},
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_token}"},
    )
    assert picker.status_code == 200, picker.text
    linked = browser.post(
        occurrence_path,
        data=_form(picker.text, "link"),
        headers=_headers(session_token, picker),
        follow_redirects=False,
    )
    assert linked.status_code == 303, linked.text
    fulfilled = browser.get(
        f"/api/recurring/items/{series_id}/occurrences/{_SERIES_PERIOD}",
        headers=api,
    ).json()
    assert fulfilled["state"] == "fulfilled"
    assert fulfilled["reserved_amount_cents"] == 0
    assert fulfilled["expense_public_id"] == fact["public_id"]
    assert fulfilled["period"] == _SERIES_PERIOD

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Expense).where(
                Expense.tenant_id == ledger_id,
                Expense.source == "手动记账",
            )
        ) == 1
        row = db.scalar(select(Expense).where(Expense.id == created_id))
        assert row is not None
        assert row.expense_time.month == 9
