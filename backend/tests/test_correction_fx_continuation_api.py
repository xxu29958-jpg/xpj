"""Historical FX recovery retains the original fact and explicit command intent."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Expense, ExpenseRevision
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_revision_service import record_confirmation_revision
from tests.expense_correction_support import idem


def _historical_expense(*, confirmed=True):
    with SessionLocal() as db:
        assert resolve_write_capability(db).home_currency_code == "CNY"
        occurred = datetime(2026, 5, 4, 2, tzinfo=UTC)
        expense = Expense(
            tenant_id="owner", source="手动记账", status="confirmed" if confirmed else "pending",
            merchant="Historical USD purchase", category="餐饮", home_currency_code="JPY",
            original_currency_code="USD", original_amount_minor=100,
            amount_cents=150 if confirmed else None,
            exchange_rate_to_cny=Decimal("150") if confirmed else None,
            exchange_rate_date=date(2026, 5, 4),
            exchange_rate_source="manual" if confirmed else None,
            fx_status="ready" if confirmed else "pending", expense_time=occurred,
            confirmed_at=occurred if confirmed else None,
        )
        db.add(expense)
        db.flush()
        if confirmed:
            record_confirmation_revision(db, expense, actor_account_id=None, actor_device_id=None)
        db.commit()
        return expense.id


def _stored_state(expense_id):
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        revisions = db.scalars(select(ExpenseRevision).where(
            ExpenseRevision.tenant_id == "owner", ExpenseRevision.expense_id == expense_id,
        ).order_by(ExpenseRevision.revision_number)).all()
        return {
            "expense": {column.key: getattr(expense, column.key) for column in Expense.__table__.columns},
            "revisions": [
                {column.key: getattr(row, column.key) for column in ExpenseRevision.__table__.columns}
                for row in revisions
            ],
        }


def _claim(headers):
    with SessionLocal() as db:
        return db.execute(select(
            ApiIdempotencyKey.operation, ApiIdempotencyKey.target_id, ApiIdempotencyKey.status,
        ).where(
            ApiIdempotencyKey.tenant_id == "owner",
            ApiIdempotencyKey.idempotency_key == headers["Idempotency-Key"],
        )).one_or_none()


def _missing_rate(response, *, currency_code, rate_date):
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"] == "exchange_rate_pending"
    assert {field: body[field] for field in ("currency_code", "home_currency_code", "rate_date")} == {
        "currency_code": currency_code, "home_currency_code": "JPY", "rate_date": rate_date,
    }


def _rate_body(*, currency_code, home_currency_code, rate_date):
    return {
        "currency_code": currency_code, "home_currency_code": home_currency_code,
        "rate_date": rate_date, "rate_to_cny": "200", "source": "manual", "expected_row_version": 0,
    }


def _save_rate(client, headers, body):
    response = client.put(
        f"/api/exchange-rates/{body['currency_code']}/{body['rate_date']}", headers=headers, json=body,
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (receipt["currency_code"], receipt["home_currency_code"], receipt["rate_date"], receipt["row_version"]) == (
        body["currency_code"], body["home_currency_code"], body["rate_date"], body["expected_row_version"] + 1,
    )
    return receipt


@pytest.mark.parametrize(("changes", "currency_code", "rate_date"), [
    pytest.param({"expense_time": "2026-05-05T02:00:00Z"}, "USD", "2026-05-05", id="changed-date"),
    pytest.param({"original_currency_code": "EUR"}, "EUR", "2026-05-04", id="changed-currency"),
])
def test_missing_historical_rate_rolls_back_until_the_same_correction_is_explicitly_retried(
    client, identity, changes, currency_code, rate_date,
):
    expense_id = _historical_expense()
    before = _stored_state(expense_id)
    url = f"/api/expenses/{expense_id}/corrections"
    headers = idem(identity.app_headers)
    body = {"expected_row_version": before["expense"]["row_version"], "reason": "Correct historical purchase", **changes}

    _missing_rate(client.post(url, headers=headers, json=body), currency_code=currency_code, rate_date=rate_date)
    assert _stored_state(expense_id) == before
    assert _claim(headers) is None

    rate_headers = idem(identity.app_headers)
    rate_body = _rate_body(currency_code=currency_code, home_currency_code="JPY", rate_date=rate_date)
    rate_receipt = _save_rate(client, rate_headers, rate_body)
    assert _save_rate(client, rate_headers, rate_body) == rate_receipt
    assert _stored_state(expense_id) == before
    assert _claim(headers) is None

    accepted = client.post(url, headers=headers, json=body)
    assert accepted.status_code == 201, accepted.text
    result = accepted.json()
    fact = result["expense"]
    assert (fact["home_currency"], fact["original_currency_code"], fact["original_amount_minor"], fact["amount_cents"]) == (
        "JPY", currency_code, 100, 200,
    )
    assert fact["exchange_rate_date"] == rate_date
    assert Decimal(fact["exchange_rate_to_cny"]) == Decimal("200")
    assert fact["row_version"] > body["expected_row_version"]
    assert fact["fact_revision"] == before["expense"]["fact_revision"] + 1
    assert result["revision"]["before"]["amount_cents"] == 150
    assert result["revision"]["after"]["amount_cents"] == 200
    assert _claim(headers) == ("correct_expense", str(expense_id), "succeeded")
    after = _stored_state(expense_id)
    assert len(after["revisions"]) == len(before["revisions"]) + 1
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == result
    assert _stored_state(expense_id) == after


@pytest.mark.parametrize(("home", "day"), [
    pytest.param("CNY", "2026-05-05", id="current-default-is-the-wrong-home"),
    pytest.param("JPY", "2026-05-04", id="manual-rate-for-the-wrong-date"),
])
def test_a_rate_outside_the_original_missing_pair_and_date_cannot_resume_the_correction(client, identity, home, day):
    expense_id = _historical_expense()
    before = _stored_state(expense_id)
    headers = idem(identity.app_headers)
    body = {"expected_row_version": before["expense"]["row_version"],
        "expense_time": "2026-05-05T02:00:00Z", "reason": "Use actual purchase date"}
    url = f"/api/expenses/{expense_id}/corrections"
    _missing_rate(client.post(url, headers=headers, json=body), currency_code="USD", rate_date="2026-05-05")
    _save_rate(client, idem(identity.app_headers), _rate_body(currency_code="USD", home_currency_code=home, rate_date=day))
    _missing_rate(client.post(url, headers=headers, json=body), currency_code="USD", rate_date="2026-05-05")
    assert _stored_state(expense_id) == before
    assert _claim(headers) is None


def test_an_intervening_correction_keeps_the_original_retry_in_occ_conflict_after_rate_recovery(client, identity):
    expense_id = _historical_expense()
    before = _stored_state(expense_id)
    url = f"/api/expenses/{expense_id}/corrections"
    headers = idem(identity.app_headers)
    body = {"expected_row_version": before["expense"]["row_version"],
        "expense_time": "2026-05-05T02:00:00Z", "reason": "Original date correction"}
    _missing_rate(client.post(url, headers=headers, json=body), currency_code="USD", rate_date="2026-05-05")
    later = client.post(url, headers=idem(identity.app_headers), json={
        "expected_row_version": body["expected_row_version"], "merchant": "Intervening writer",
        "reason": "Correct merchant separately",
    })
    assert later.status_code == 201, later.text
    current = _stored_state(expense_id)
    _save_rate(client, idem(identity.app_headers), _rate_body(
        currency_code="USD", home_currency_code="JPY", rate_date="2026-05-05",
    ))
    assert _stored_state(expense_id) == current
    refused = client.post(url, headers=headers, json=body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == "state_conflict"
    assert _stored_state(expense_id) == current
    assert _claim(headers) is None


def test_pending_confirmation_requires_review_of_a_new_historical_conversion_after_rate_save(client, identity):
    expense_id = _historical_expense(confirmed=False)
    before = _stored_state(expense_id)
    url = f"/api/expenses/{expense_id}/confirm"
    headers = idem(identity.app_headers)
    body = {"expected_row_version": before["expense"]["row_version"]}
    _missing_rate(client.post(url, headers=headers, json=body), currency_code="USD", rate_date="2026-05-04")
    assert _stored_state(expense_id) == before
    assert _claim(headers) is None
    _save_rate(client, idem(identity.app_headers), _rate_body(
        currency_code="USD", home_currency_code="JPY", rate_date="2026-05-04",
    ))
    assert _stored_state(expense_id) == before
    assert _claim(headers) is None
    _missing_rate(client.post(url, headers=headers, json=body), currency_code="USD", rate_date="2026-05-04")
    reviewed = client.patch(f"/api/expenses/{expense_id}", headers=idem(identity.app_headers), json={
        **body, "original_currency_code": "USD", "original_amount_minor": 100,
    })
    assert reviewed.status_code == 200, reviewed.text
    assert (reviewed.json()["status"], reviewed.json()["fx_status"], reviewed.json()["amount_cents"]) == (
        "pending", "ready", 200,
    )
    assert reviewed.json()["row_version"] > body["expected_row_version"]
    assert _claim(headers) is None
    headers = idem(identity.app_headers)
    body = {"expected_row_version": reviewed.json()["row_version"]}
    accepted = client.post(url, headers=headers, json=body)
    assert accepted.status_code == 200, accepted.text
    fact = accepted.json()
    assert (fact["status"], fact["home_currency"], fact["original_currency_code"], fact["amount_cents"]) == (
        "confirmed", "JPY", "USD", 200,
    )
    assert fact["fact_revision"] == 1
    assert _claim(headers) == ("confirm_expense", str(expense_id), "succeeded")
    after = _stored_state(expense_id)
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == fact
    assert _stored_state(expense_id) == after
