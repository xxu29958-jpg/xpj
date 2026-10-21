"""Real PostgreSQL contracts for accepted async work and legacy completion."""

import json

import pytest
from sqlalchemy import func, inspect, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import ApiIdempotencyKey, BackgroundTask, Expense, OcrFact
from app.services import background_task_worker
from app.services.expense_ocr_task_service import submit_expense_ocr_task, wait_legacy_ocr_result
from app.services.expense_service import _enrich, _ocr
from app.services.idempotency import fingerprint_request
from tests.test_pending_enrichment_task_service import _ocr_result, _seed_pending_enrichment_task

pytestmark = pytest.mark.real_db


@pytest.fixture
def retry_input(identity, monkeypatch):
    expense_id, predecessor, seed_task_id = _seed_pending_enrichment_task()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, seed_task_id)
        account_id = task.initiated_by_account_id
        task.status = "completed"
        db.commit()
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *args: None)
    return {"expense_id": expense_id, "tenant_id": "owner", "initiator_account_id": account_id,
        "initiator_device_id": None, "expected_row_version": predecessor,
        "request_expected_row_version": 0, "idempotency_key": "original-ocr-key"}


@pytest.mark.parametrize("legacy", [False, True])
def test_acceptance_replay_and_atomic_completion_keep_protocols_distinct(retry_input, monkeypatch, legacy):
    calls = []

    def extract(expense):
        assert inspect(expense).transient
        calls.append(expense.id)
        return _ocr_result()[0].result

    monkeypatch.setattr(_ocr, "extract_ocr_result", extract)
    with SessionLocal() as db:
        accepted = submit_expense_ocr_task(db, **retry_input, legacy=legacy)
        task_id, public_id = accepted.id, accepted.public_id
        payload = json.loads(accepted.input_payload_json)
        assert accepted.status == "queued" and accepted.result_summary_json is None
        claim = db.scalar(select(ApiIdempotencyKey))
        assert claim.status == ("in_progress" if legacy else "succeeded")
        assert (claim.resource_type, claim.resource_id) == ("background_task", public_id)
        assert db.get(Expense, retry_input["expense_id"]).row_version == retry_input["expected_row_version"]
        repeated = submit_expense_ocr_task(db, **retry_input, legacy=legacy)
        assert repeated.public_id == public_id
        assert db.scalar(select(func.count()).select_from(BackgroundTask)
            .where(BackgroundTask.task_type == "expense_ocr_retry")) == 1
    background_task_worker.run_task(task_id, payload)
    with SessionLocal() as db:
        task, claim = db.get(BackgroundTask, task_id), db.scalar(select(ApiIdempotencyKey))
        assert task.status == "completed" and claim.status == "succeeded"
        outcome = json.loads(task.result_summary_json)
        assert outcome["row_version"] == retry_input["expected_row_version"] + 1
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 1
        replay = submit_expense_ocr_task(db, **retry_input, legacy=legacy)
        if legacy:
            assert isinstance(replay, Expense) and replay.row_version == outcome["row_version"]
            assert claim.resource_type == "expense"
            assert wait_legacy_ocr_result(db, task).row_version == outcome["row_version"]
        else:
            assert replay.public_id == public_id and claim.resource_type == "background_task"
        operation = "retry_ocr" if legacy else "retry_ocr_async"
        assert claim.request_fingerprint == fingerprint_request(operation=operation,
            target_id=str(retry_input["expense_id"]), body={}, expected_row_version=0)
    assert calls == [retry_input["expense_id"]]


def test_legacy_timeout_does_not_acknowledge_queue_or_hold_database(retry_input):
    with SessionLocal() as db:
        task = submit_expense_ocr_task(db, **retry_input, legacy=True)
        with pytest.raises(AppError, match="其它图片") as caught:
            wait_legacy_ocr_result(db, task, timeout_seconds=0)
        assert caught.value.error == "ocr_busy" and not db.in_transaction()
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey)).status == "in_progress"
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 0


def test_legacy_failed_attempt_remains_retryable_without_acknowledging_failure(retry_input, monkeypatch):
    def unavailable(_expense):
        raise AppError("ocr_model_missing", status_code=503)

    monkeypatch.setattr(_ocr, "extract_ocr_result", unavailable)
    with SessionLocal() as db:
        first = submit_expense_ocr_task(db, **retry_input, legacy=True)
        first_id, payload = first.id, json.loads(first.input_payload_json)
    background_task_worker.run_task(first_id, payload)
    with SessionLocal() as db:
        first = db.get(BackgroundTask, first_id)
        with pytest.raises(AppError) as caught:
            wait_legacy_ocr_result(db, first)
        assert caught.value.error == "ocr_model_missing"
        assert db.scalar(select(ApiIdempotencyKey)).status == "in_progress"
        second = submit_expense_ocr_task(db, **retry_input, legacy=True)
        second_id, payload = second.id, json.loads(second.input_payload_json)
        assert second_id != first_id
    monkeypatch.setattr(_ocr, "extract_ocr_result", lambda _expense: _ocr_result()[0].result)
    background_task_worker.run_task(second_id, payload)
    with SessionLocal() as db:
        assert db.get(BackgroundTask, first_id).status == "failed"
        assert db.get(BackgroundTask, second_id).status == "completed"
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 1
        assert db.get(Expense, retry_input["expense_id"]).row_version == retry_input["expected_row_version"] + 1


def test_same_key_with_changed_predecessor_cannot_enqueue_another_intent(retry_input):
    with SessionLocal() as db:
        submit_expense_ocr_task(db, **retry_input)
        with pytest.raises(AppError) as caught:
            submit_expense_ocr_task(db, **{**retry_input, "request_expected_row_version": 99})
        assert caught.value.error == "idempotency_key_reused"
        assert db.scalar(select(func.count()).select_from(BackgroundTask)
            .where(BackgroundTask.task_type == "expense_ocr_retry")) == 1
