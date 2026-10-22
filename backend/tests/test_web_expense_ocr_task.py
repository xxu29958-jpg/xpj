"""Queued OCR remains observable and cancellable beside the original bill."""

import json

import pytest
from api_contract_helpers import patch_expense
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, BackgroundTask
from app.services import background_task_worker
from app.services.expense_service import _ocr
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_ocr_retry import _open_retry, _record, _suggestion

pytestmark = pytest.mark.real_db


@pytest.mark.parametrize("later_action", ["edit", "cancel"])
def test_web_queue_preserves_original_and_exposes_scoped_status_and_cancellation(web_client, identity, monkeypatch, later_action):
    expense_id, action, fields = _open_retry(web_client, identity)
    before = _record(expense_id)
    submissions, calls = [], []
    monkeypatch.setattr("app.services.background_task_executor.submit_task",
        lambda task_id, payload, **kwargs: submissions.append((task_id, payload)))
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    monkeypatch.setattr(_ocr, "extract_ocr_result", lambda expense: calls.append(expense.id) or _suggestion())
    accepted = web_client.post(action, data=fields, follow_redirects=False)
    assert accepted.status_code == 303 and _record(expense_id) == before and not calls
    task_id, payload = submissions[0]
    with SessionLocal() as db:
        public_id = db.get(BackgroundTask, task_id).public_id
    status_path = f"/web/expenses/{expense_id}/ocr/tasks/{public_id}"
    page = web_client.get(accepted.headers["location"])
    assert "data-expense-ocr-watch" in page.text and "取消本次识别" in page.text
    assert public_id in page.text and "expense-ocr-watch.js" in page.text
    queued = web_client.get(status_path + "?ledger_id=owner")
    assert queued.status_code == 200 and queued.json()["status"] == "queued"
    assert queued.json()["source_expense_id"] == expense_id
    assert web_client.get(status_path + "?ledger_id=tester_1").status_code in {403, 404}
    assert web_client.get(f"/web/expenses/{expense_id+99}/ocr/tasks/{public_id}?ledger_id=owner").status_code == 404
    if later_action == "edit":
        edited = patch_expense(web_client, expense_id, headers=identity.app_headers,
            fields={"merchant": "用户正在核对", "amount_cents": 1899})
        assert edited.status_code == 200
    else:
        cancel = status_path + "/cancel"
        assert web_client.post(cancel, data=hidden_post_forms(page.text)[cancel], follow_redirects=False).status_code == 303
    current = _record(expense_id)
    background_task_worker.run_task(task_id, payload)
    status = web_client.get(status_path + "?ledger_id=owner").json()
    if later_action == "edit":
        assert status["status"] == "completed" and status["result_summary"]["outcome"] == "conflict"
    else:
        assert status["status"] == "cancelled"
    assert _record(expense_id) == current and not calls


def test_new_api_acknowledges_a_task_and_does_not_impersonate_the_legacy_bill_response(web_client, identity, monkeypatch):
    expense_id, _action, fields = _open_retry(web_client, identity)
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    result = web_client.post(f"/api/expenses/{expense_id}/ocr/tasks",
        headers={**identity.app_headers, "Idempotency-Key": "new-task-key"},
        json={"expected_row_version": int(fields["expected_row_version"])})
    assert result.status_code == 202, result.text
    assert result.json()["task_type"] == "expense_ocr_retry" and result.json()["status"] == "queued"
    assert "row_version" not in result.json()
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "new-task-key"))
        assert claim.operation == "retry_ocr_async" and claim.resource_type == "background_task"


def test_old_web_draft_recovers_completed_legacy_key_without_new_task_or_second_recognition(web_client, identity, monkeypatch):
    expense_id, action, fields = _open_retry(web_client, identity)
    calls = []
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    monkeypatch.setattr(_ocr, "_active_provider_name", lambda: "mock")
    monkeypatch.setattr(_ocr, "extract_ocr_result", lambda expense: calls.append(expense.id) or _suggestion())
    original = web_client.post(f"/api/expenses/{expense_id}/ocr/retry",
        headers={**identity.app_headers, "Idempotency-Key": fields["idempotency_key"]},
        json={"expected_row_version": int(fields["expected_row_version"])})
    assert original.status_code == 200, original.text
    committed = _record(expense_id)
    repeated = web_client.post(action, data=fields, follow_redirects=False)
    assert repeated.status_code == 303 and _record(expense_id) == committed and calls == [expense_id]
    with SessionLocal() as db:
        tasks = list(db.scalars(select(BackgroundTask).where(BackgroundTask.task_type == "expense_ocr_retry")))
        assert len(tasks) == 1 and json.loads(tasks[0].input_payload_json)["legacy"] is True
