"""Missing historical rates keep the original debt/refund form available to finish."""

import re
from uuid import uuid4

import pytest
from _web_native_form_support import hidden_post_forms
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt, ExpenseOffsetFact
from tests._runtime_protocol import negotiated_headers

pytestmark = pytest.mark.real_db


def _hidden(html, action, *, marker=None):
    forms = [match.group() for match in re.finditer(r"<form\b[^>]*>.*?</form>", html, re.S)]
    form = next(form for form in forms if f'action="{action}"' in form and (marker is None or marker in form))
    return hidden_post_forms(form)[action]


def test_native_foreign_debt_can_save_missing_rate_then_submit_original_once(web_client):
    action = "/web/debts"
    original = {**_hidden(web_client.get("/web/debts/new?ledger_id=owner").text, action),
        "direction": "i_owe", "counterparty_label": "Original foreign debt", "note": "preserved note",
        "amount_major": "12.50", "currency_code": "USD", "event_time": "2026-05-06",
        "debt_kind": "installment", "installment_count": "3", "installment_period_months": "1"}
    failed = web_client.post(action, data=original, follow_redirects=False)
    assert failed.status_code == 409, failed.text
    assert 'formaction="/web/debts/rate"' in failed.text
    rate_form = {**original, **_hidden(failed.text, action), "fx_rate_to_cny": "8"}
    assert rate_form["idempotency_key"] == original["idempotency_key"]
    saved = web_client.post("/web/debts/rate", data=rate_form)
    assert saved.status_code == 200, saved.text
    assert "原操作尚未保存" in saved.text
    assert 'value="12.50"' in saved.text and "preserved note" in saved.text
    retained = _hidden(saved.text, action)
    assert retained["idempotency_key"] == original["idempotency_key"]
    with SessionLocal() as db:
        assert db.scalar(select(Debt).where(Debt.counterparty_label == "Original foreign debt")) is None
    first = web_client.post(action, data={**original, **retained}, follow_redirects=False)
    replay = web_client.post(action, data={**original, **retained}, follow_redirects=False)
    assert first.status_code == replay.status_code == 303
    assert first.headers["location"] == replay.headers["location"]
    with SessionLocal() as db:
        debts = list(db.scalars(select(Debt).where(Debt.counterparty_label == "Original foreign debt")))
        assert len(debts) == 1
        assert (debts[0].principal_amount_cents, debts[0].original_currency_code, debts[0].original_amount_minor) == (10000, "USD", 1250)


def test_native_foreign_refund_rate_keeps_original_occ_key_and_does_not_publish_refund(web_client, identity):
    seeded = web_client.put("/api/exchange-rates/USD/2026-05-04",
        headers={**negotiated_headers(web_client, identity.app_headers), "Idempotency-Key": str(uuid4())},
        json={"expected_row_version": 0, "currency_code": "USD", "home_currency_code": "CNY",
            "rate_date": "2026-05-04", "rate_to_cny": "7", "source": "manual"})
    assert seeded.status_code == 200, seeded.text
    created = web_client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"client_ref": str(uuid4()), "home_currency_code": "CNY", "original_currency_code": "USD",
            "original_amount_minor": 10000, "expense_time": "2026-05-04T08:00:00Z",
            "merchant": "Foreign refund", "category": "购物"})
    assert created.status_code == 200, created.text
    expense = created.json()
    action = f"/web/expenses/{expense['id']}/offsets"
    page = web_client.get(f"/web/expenses/{expense['id']}/edit?ledger_id=owner")
    original = {**_hidden(page.text, action, marker='id="offset-amount"'),
        "kind": "refund", "original_amount": "25.00", "accounting_date": "2026-05-05", "reason": "original reason"}
    failed = web_client.post(action, data=original)
    assert failed.status_code == 409, failed.text
    rate_action = f"/web/expenses/{expense['id']}/offset-rate"
    assert f'formaction="{rate_action}"' in failed.text
    retained = _hidden(failed.text, action, marker='id="offset-amount"')
    assert all(retained[key] == original[key] for key in ("expected_row_version", "idempotency_key"))
    saved = web_client.post(rate_action, data={**original, **retained, "fx_rate_to_cny": "8"})
    assert saved.status_code == 200, saved.text
    assert "原操作尚未保存" in saved.text and 'value="25.00"' in saved.text and 'value="original reason"' in saved.text
    retained = _hidden(saved.text, action, marker='id="offset-amount"')
    assert all(retained[key] == original[key] for key in ("expected_row_version", "idempotency_key"))
    with SessionLocal() as db:
        assert db.scalar(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense["id"])) is None
    first = web_client.post(action, data={**original, **retained}, follow_redirects=False)
    replay = web_client.post(action, data={**original, **retained}, follow_redirects=False)
    assert first.status_code == replay.status_code == 303
    with SessionLocal() as db:
        offsets = list(db.scalars(select(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense["id"])))
        assert len(offsets) == 1
        assert (offsets[0].original_amount_minor, offsets[0].amount_cents) == (2500, 20000)
