"""Native Web foreign-bill recovery stays on the bill and preserves the review draft."""

import json
import re
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from _web_native_form_support import hidden_post_forms
from sqlalchemy import select

from app.database import SessionLocal
from app.models import BackgroundTask, CsvImportBatch, CsvImportRow, Expense
from app.services import background_task_worker, pending_fx_task_service
from app.services.fx_rate_provider import EcbDailyRates, FxFetchError
from tests.test_foreign_bill_continuation import _import_foreign_bill

pytestmark = pytest.mark.real_db


@pytest.fixture(autouse=True)
def captured_submissions(monkeypatch):
    """Keep each durable task queued until this journey explicitly runs its worker."""
    submitted = Mock()
    monkeypatch.setattr("app.services.background_task_executor.submit_task", submitted)
    return submitted


def _form(html, expense):
    values = hidden_post_forms(html)[f"/web/expenses/{expense['id']}/save"]
    return {**values, "amount_yuan": "123.45", "merchant": "Unsent cafe", "category": "交通",
        "note": "keep my note", "tags": "trip", "expense_time": "2026-05-04T00:30", "manual_exchange_rate": ""}


def test_web_import_pending_and_health_link_to_current_foreign_bill(web_client, identity, captured_submissions):
    bill = _import_foreign_bill(web_client, identity)
    captured_submissions.assert_called_once()
    with SessionLocal() as db:
        batch_id = db.scalar(select(CsvImportBatch.public_id).join(CsvImportRow, CsvImportRow.batch_id == CsvImportBatch.id)
            .where(CsvImportRow.expense_id == bill["id"]))
    pending = web_client.get("/web/pending?ledger_id=owner&filter=missing_fx")
    assert pending.status_code == 200
    assert f'data-expense-id="{bill["id"]}"' in pending.text
    assert "待补汇率" in pending.text
    health = web_client.get("/web/data-quality?ledger_id=owner")
    assert "1 条待补汇率" in health.text and "filter=missing_fx" in health.text
    batch = web_client.get(f"/web/import/{batch_id}?ledger_id=owner")
    assert f'data-import-current-expense="{bill["id"]}"' in batch.text
    assert f'/web/expenses/{bill["id"]}/edit?ledger_id=owner' in batch.text
    assert "123.45" in batch.text and "USD" in batch.text and "待补汇率" in batch.text
    for fragment in ("", "&fragment=1"):
        page = web_client.get(f"/web/expenses/{bill['id']}/edit?ledger_id=owner{fragment}")
        assert 'data-expense-fx-state="queued"' in page.text
        assert "刷新汇率状态" in page.text and 'name="manual_exchange_rate"' in page.text
        assert "/owner/fx" not in page.text


def test_web_fx_failure_retry_and_completion_keep_original_form_until_explicit_load(
    web_client, identity, monkeypatch, captured_submissions,
):
    bill = _import_foreign_bill(web_client, identity)
    captured_submissions.assert_called_once()
    edit = f"/web/expenses/{bill['id']}/edit?ledger_id=owner"
    submitted = _form(web_client.get(edit).text, bill)
    original_key = submitted["idempotency_key"]
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, payload, **kwargs: background_task_worker.run_task(task_id, payload, kwargs["registry"]))

    def unavailable(_original):
        raise FxFetchError("provider unavailable")

    monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference", unavailable)
    failed = web_client.post(f"/web/expenses/{bill['id']}/fx", data=submitted)
    assert failed.status_code == 200, failed.text
    assert 'data-expense-fx-state="failed"' in failed.text
    assert "重试获取汇率" in failed.text and 'name="manual_exchange_rate"' in failed.text
    monkeypatch.setattr(pending_fx_task_service, "fetch_pending_fx_reference",
        lambda _original: EcbDailyRates(date(2026, 4, 30), {"EUR": Decimal(1), "USD": Decimal(1), "CNY": Decimal(7)}))
    completed = web_client.post(f"/web/expenses/{bill['id']}/fx", data={**submitted, "fragment": "1"})
    assert completed.status_code == 200, completed.text
    refreshed = web_client.post(f"/web/expenses/{bill['id']}/fx-status", data={**submitted, "fragment": "1"})
    assert refreshed.status_code == 200, refreshed.text
    for response in (completed, refreshed):
        assert 'data-expense-fx-state="completed"' in response.text
        assert "keep my note" in response.text and 'value="Unsent cafe"' in response.text
        assert f'name="expected_row_version" value="{bill["row_version"]}"' in response.text
        assert f'name="idempotency_key" value="{original_key}"' in response.text
        assert "载入最新账单" in response.text and "未保存" in response.text
        assert "2026-04-30" in response.text and "2026-05-04" in response.text
    with SessionLocal() as db:
        expense = db.get(Expense, bill["id"])
        assert (expense.status, expense.row_version, expense.amount_cents) == ("pending", bill["row_version"] + 1, 86415)
        assert expense.merchant == bill["merchant"] and expense.note != "keep my note"
        tasks = list(db.scalars(select(BackgroundTask).where(BackgroundTask.source_expense_id == bill["id"])))
        assert len(tasks) == 2
    loaded = web_client.get(edit)
    assert re.search(rf'name="expected_row_version" value="{bill["row_version"] + 1}"', loaded.text)
    assert "确认入账" in loaded.text


def test_web_status_refresh_does_not_publish_an_unsaved_currency_edit(web_client, identity):
    bill = _import_foreign_bill(web_client, identity)
    edit = f"/web/expenses/{bill['id']}/edit?ledger_id=owner"
    submitted = {**_form(web_client.get(edit).text, bill), "amount_yuan": "999.99", "expense_time": "2026-05-06T10:00"}
    refreshed = web_client.post(f"/web/expenses/{bill['id']}/fx-status", data=submitted)
    assert refreshed.status_code == 200, refreshed.text
    assert 'value="999.99"' in refreshed.text and 'value="2026-05-06T10:00"' in refreshed.text
    with SessionLocal() as db:
        current = db.get(Expense, bill["id"])
        assert (current.original_amount_minor, current.row_version) == (12345, bill["row_version"])
        assert len(list(db.scalars(select(BackgroundTask).where(BackgroundTask.source_expense_id == bill["id"])))) == 1


def test_web_saving_new_bill_date_stages_new_fx_input_with_real_web_actor(web_client, identity):
    bill = _import_foreign_bill(web_client, identity)
    submitted = {**_form(web_client.get(f"/web/expenses/{bill['id']}/edit?ledger_id=owner").text, bill),
        "expense_time": "2026-05-06T10:00"}
    response = web_client.post(f"/web/expenses/{bill['id']}/save", data=submitted, follow_redirects=False)
    assert response.status_code == 303, response.text
    with SessionLocal() as db:
        tasks = list(db.scalars(select(BackgroundTask).where(BackgroundTask.source_expense_id == bill["id"])
            .order_by(BackgroundTask.id)))
        assert len(tasks) == 2
        old, new = tasks
        assert old.initiated_by_account_id is not None
        assert new.initiated_by_account_id == old.initiated_by_account_id
        assert new.initiated_by_device_id is None  # the real LocalOnly Web actor, no invented app Device
        original = json.loads(new.input_payload_json)
        assert (original["rate_date"], original["expected_row_version"], original["expense_id"]) == (
            "2026-05-06", bill["row_version"] + 1, bill["id"])
        assert db.get(Expense, bill["id"]).status == "pending"
