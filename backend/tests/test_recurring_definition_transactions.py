"""A definition or recording receipt must never be accepted without its evidence."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import RecurringItem, RecurringItemRevision, RecurringOccurrence
from app.services import recurring_item_command_service as commands
from app.services import recurring_occurrence_command as occurrences
from tests.test_recurring_definition_history import _create, _headers, _history, _payment

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize("operation", ["create", "edit"])
def test_definition_append_failure_rolls_back_original_command_and_same_key_can_retry(client, identity, monkeypatch, operation):
    original = _create(client, identity, "CNY")[2] if operation == "edit" else None
    key = str(uuid4())
    body = {"merchant": "事务原定义", "home_currency_code": "CNY", "baseline_amount_cents": 2300}
    path = "/api/recurring/items"
    if original:
        path += f'/{original["public_id"]}'
        body["expected_row_version"] = original["row_version"]
    request = client.patch if original else client.post
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError("definition persistence unavailable")
        patch.setattr(commands, "record_recurring_item_revision", fail)
        with pytest.raises(RuntimeError, match="definition persistence unavailable"):
            request(path, headers=_headers(client, identity, key), json=body)
    with SessionLocal() as db:
        rows = db.scalars(select(RecurringItem).where(RecurringItem.tenant_id == "owner")).all()
        assert len(rows) == (1 if original else 0)
        if original:
            assert (rows[0].row_version, rows[0].baseline_amount_cents, rows[0].merchant_name) == (1, 1200, "原固定支出")
        assert db.scalar(select(func.count()).select_from(RecurringItemRevision)) == (1 if original else 0)
    accepted = request(path, headers=_headers(client, identity, key), json=body)
    assert accepted.status_code == (200 if original else 201), accepted.text
    receipt = accepted.json()
    replay = request(path, headers=_headers(client, identity, key), json=body)
    assert replay.json() == receipt
    history = _history(client, identity, receipt["public_id"])["items"]
    assert len(history) == (2 if original else 1)
    assert history[0]["snapshot"]["baseline_amount_cents"] == 2300
    assert history[0]["row_version"] == receipt["row_version"]


def test_first_record_receipt_failure_leaves_no_basis_or_payment_change_and_original_intent_retries(client, identity, monkeypatch):
    series = _create(client, identity, "CNY")[2]
    payment = _payment(client, identity)
    key = str(uuid4())
    body = {"action": "link", "expense_public_id": payment["public_id"],
        "expected_expense_row_version": payment["row_version"], "expected_row_version": 0,
        "expected_series_row_version": series["row_version"]}
    path = f'/api/recurring/items/{series["public_id"]}/occurrences/2026-05'
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise RuntimeError("recording receipt unavailable")
        patch.setattr(occurrences, "mark_idempotency_succeeded", fail)
        with pytest.raises(RuntimeError, match="recording receipt unavailable"):
            client.put(path, headers=_headers(client, identity, key), json=body)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RecurringOccurrence)) == 0
    assert client.get(f'/api/expenses/{payment["id"]}', headers=identity.app_headers).json()["row_version"] == payment["row_version"]
    accepted = client.put(path, headers=_headers(client, identity, key), json=body)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["recorded_definition"]["series_row_version"] == series["row_version"]
    assert receipt["recorded_definition"]["snapshot"]["baseline_amount_cents"] == 1200
    assert client.put(path, headers=_headers(client, identity, key), json=body).json() == receipt
