"""CSV row commit and FX task execution have distinct failure outcomes."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import BackgroundTask, CsvImportRow, Expense
from app.services.csv_import_batch_service import _apply
from app.services.identity_service import authenticate_session_token

pytestmark = pytest.mark.real_db


def _create_foreign_batch(client, identity):
    content = (
        "home_currency_code,amount_cents,original_currency_code,original_amount_minor,expense_time,merchant,category\n"
        "CNY,,USD,12345,2026-05-03T16:30:00Z,Historical foreign receipt,交通\n"
    )
    response = client.post(
        "/api/imports/csv", headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", content.encode(), "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert (response.json()["valid_rows"], response.json()["error_rows"]) == (1, 0)
    return f"/api/imports/csv/{response.json()['public_id']}"


def test_csv_executor_refusal_preserves_committed_bill_row_and_original_task(client, identity, monkeypatch):
    committed_before_dispatch = []

    def refuse_execution(*_args, **_kwargs):
        # Inspect from an independent connection before refusing executor dispatch.
        with SessionLocal() as db:
            row = db.scalar(select(CsvImportRow).where(CsvImportRow.tenant_id == "owner"))
            assert row.status == "applied" and row.expense_id is not None
            task = db.scalar(select(BackgroundTask).where(BackgroundTask.task_type == "expense_fx"))
            assert task.source_expense_id == row.expense_id and task.status == "queued"
            committed_before_dispatch.append(task.public_id)
        raise RuntimeError("executor refused the committed FX task")

    monkeypatch.setattr("app.services.background_task_executor.submit_task", refuse_execution)
    endpoint = _create_foreign_batch(client, identity)
    applied = client.post(f"{endpoint}/apply", headers=identity.app_headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["inserted_count"] == 1
    assert applied.json()["batch"]["status"] == "applied"
    replay = client.post(f"{endpoint}/apply", headers=identity.app_headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["inserted_count"] == 0
    # The executor barrier catches exceptions, so the in-hook assertions alone
    # cannot prove the independent committed-state observation actually succeeded.
    assert len(committed_before_dispatch) == 1
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.app_token, {"app"})
        row = db.scalars(select(CsvImportRow).where(CsvImportRow.tenant_id == auth.tenant_id)).one()
        expense = db.scalars(select(Expense).where(Expense.tenant_id == auth.tenant_id)).one()
        task = db.scalars(select(BackgroundTask).where(BackgroundTask.task_type == "expense_fx")).one()
        assert task.public_id == committed_before_dispatch[0]
        assert (row.status, row.expense_id, row.error_code) == ("applied", expense.id, None)
        assert (expense.status, expense.fx_status, expense.amount_cents, expense.row_version) == ("pending", "pending", None, 1)
        assert (task.status, task.error_code, task.source_expense_id) == ("failed", "task_submission_failed", expense.id)
        assert (task.tenant_id, task.initiated_by_account_id, task.initiated_by_device_id) == (
            auth.tenant_id, auth.account_id, auth.device_id,
        )
        assert task.input_payload_json is not None


def test_csv_failure_after_task_staging_rolls_back_bill_and_task_together(client, identity, monkeypatch):
    prepare = _apply.prepare_pending_expense_fx
    staged = []

    def fail_after_staging(db, **kwargs):
        prepared = prepare(db, **kwargs)
        assert prepared is not None
        staged.append(prepared.task_public_id)
        raise IntegrityError("CSV write after task staging", {}, ValueError("synthetic row constraint failure"))

    monkeypatch.setattr(_apply, "prepare_pending_expense_fx", fail_after_staging)
    endpoint = _create_foreign_batch(client, identity)
    response = client.post(f"{endpoint}/apply", headers=identity.app_headers)
    assert response.status_code == 200, response.text
    assert response.json()["inserted_count"] == 0
    assert response.json()["batch"]["status"] == "applied_with_errors"
    assert len(staged) == 1
    with SessionLocal() as db:
        row = db.scalars(select(CsvImportRow).where(CsvImportRow.tenant_id == "owner")).one()
        assert (row.status, row.expense_id, row.error_code) == ("insert_failed", None, "insert_failed")
        assert db.scalar(select(Expense.id).where(Expense.tenant_id == "owner")) is None
        assert db.scalar(select(BackgroundTask.id).where(BackgroundTask.public_id == staged[0])) is None
