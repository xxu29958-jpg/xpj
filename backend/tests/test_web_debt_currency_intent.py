"""Browser debt forms preserve the user's captured money and retry identity."""

import re
from datetime import date
from html import unescape
from uuid import uuid4

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Debt
from app.schemas import ExchangeRateRequest
from app.services.exchange_rate_service import set_exchange_rate_idempotently


def _hidden(page: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', page)
    assert match is not None
    return unescape(match.group(1))


def _form(web_client) -> dict[str, str]:
    page = web_client.get("/web/debts/new?ledger_id=owner")
    assert page.status_code == 200
    return {
        "csrf_token": "test-client-bypasses-middleware-check", "ledger_id": "owner",
        "idempotency_key": _hidden(page.text, "idempotency_key"),
        "home_currency_code": _hidden(page.text, "home_currency_code"),
        "direction": "owed_to_me", "counterparty_label": "Alex", "currency_code": "CNY",
        "amount_major": "12", "event_time": "2026-09-08", "note": "保留原意图",
    }


def test_error_and_retry_keep_the_captured_currency_amount_and_key(web_client):
    form = {**_form(web_client), "home_currency_code": "JPY", "currency_code": "USD", "amount_major": "1.005"}
    rejected = web_client.post("/web/debts", data=form)
    assert rejected.status_code == 422
    assert _hidden(rejected.text, "idempotency_key") == form["idempotency_key"]
    assert _hidden(rejected.text, "home_currency_code") == "JPY"
    assert 'value="1.005"' in rejected.text
    assert re.findall(r'<option value="([A-Z]+)" selected>', rejected.text) == ["USD"]
    assert "金额（所选币种）" in rejected.text
    assert "按发生日折算为 JPY" in rejected.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 0
        set_exchange_rate_idempotently(db, tenant_id="owner", actor_account_id=None, idempotency_key=str(uuid4()),
            payload=ExchangeRateRequest(currency_code="USD", home_currency_code="JPY",
                rate_date=date(2026, 9, 8), rate_to_cny="150", expected_row_version=0))
    repaired = {**form, "amount_major": "1.25"}
    saved = web_client.post("/web/debts", data=repaired)
    assert saved.status_code == 200
    assert web_client.post("/web/debts", data=repaired).status_code == 200
    with SessionLocal() as db:
        debt = db.scalar(select(Debt))
        assert debt.home_currency_code == "JPY"
        assert debt.principal_amount_cents == 188
        assert debt.original_currency_code == "USD"
        assert debt.original_amount_minor == 125
        assert db.scalar(select(func.count()).select_from(Debt)) == 1


def test_editing_an_already_saved_form_requires_review_before_a_new_debt(web_client):
    form = _form(web_client)
    assert web_client.post("/web/debts", data=form).status_code == 200
    changed = {**form, "amount_major": "13"}
    review = web_client.post("/web/debts", data=changed)
    assert review.status_code == 422
    assert "请先核对原记录；再次保存将新增一笔往来" in review.text
    next_key = _hidden(review.text, "idempotency_key")
    assert next_key != form["idempotency_key"]
    assert 'value="13"' in review.text
    with SessionLocal() as db:
        assert db.scalars(select(Debt.principal_amount_cents)).all() == [1200]
    saved = web_client.post("/web/debts", data={**changed, "idempotency_key": next_key})
    assert saved.status_code == 200
    with SessionLocal() as db:
        assert sorted(db.scalars(select(Debt.principal_amount_cents)).all()) == [1200, 1300]


def test_a_legacy_form_without_currency_is_reviewed_before_it_can_write(web_client):
    form = _form(web_client)
    form.pop("home_currency_code")
    review = web_client.post("/web/debts", data=form)
    assert review.status_code == 422
    assert "请核对金额、原币和记账币种后再次保存" in review.text
    assert _hidden(review.text, "idempotency_key") == form["idempotency_key"]
    assert _hidden(review.text, "home_currency_code") == "CNY"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Debt)) == 0
