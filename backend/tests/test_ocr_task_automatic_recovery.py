"""Original task recovery survives lost wakeups without resetting identity or retry bounds."""

import json
from dataclasses import replace
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask, Expense, LedgerMember, OcrFact
from app.services import background_task_admission as admission
from app.services import background_task_executor as executor
from app.services import background_task_handler_api as handler_api
from app.services import background_task_recovery_service as recovery
from app.services import background_task_worker as worker
from app.services.currency_binding_service import resolve_write_capability
from app.services.expense_service import _enrich
from app.services.optimistic_concurrency import bump_row_version
from app.services.pending_enrichment_task_service import resume_pending_expense_enrichment
from app.services.time_service import now_utc
from tests.test_pending_enrichment_task_service import _ocr_result, _seed_pending_enrichment_task

pytestmark = pytest.mark.real_db


def _original(status="queued"):
    expense_id, predecessor, task_id = _seed_pending_enrichment_task()
    payload = {"expense_id": expense_id, "tenant_id": "owner", "timezone_name": "Asia/Shanghai",
        "expected_row_version": predecessor}
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        task.status, task.source_expense_id, task.input_payload_json = status, expense_id, json.dumps(payload)
        db.commit()
        return task_id, task.public_id, payload


@pytest.fixture
def clock(monkeypatch):
    value = [now_utc()]
    for module in (handler_api, recovery, worker, executor):
        monkeypatch.setattr(module, "now_utc", lambda: value[0])
    return value


def test_old_capacity_blocked_failures_do_not_starve_already_admitted_work(identity, monkeypatch, clock):
    historical = [_original("failed")[0] for _ in range(16)]
    admitted = [_original()[0] for _ in range(8)]
    with SessionLocal() as db:
        for task in db.scalars(select(BackgroundTask).where(BackgroundTask.id.in_(historical))):
            task.error_code = "orphaned_after_restart"
            task.created_at = clock[0] - timedelta(hours=1)
        db.commit()
    settings = replace(admission.get_settings(), background_task_max_active=8)
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: _ocr_result())
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    monkeypatch.setattr(executor, "submit_task", lambda identifier, original, *, registry, runner: runner(identifier, original, registry))
    assert recovery.resume_due_ocr_tasks() == len(admitted)
    with SessionLocal() as db:
        assert all(db.get(BackgroundTask, identifier).status == "completed" for identifier in admitted)
    for _ in range(2):
        clock[0] += timedelta(seconds=11)
        assert recovery.resume_due_ocr_tasks() == 8
    with SessionLocal() as db:
        tasks = list(db.scalars(select(BackgroundTask)))
        assert len(tasks) == 24 and all(task.status == "completed" for task in tasks)
        assert all(task.recovery_attempts == 1 for task in tasks if task.id in historical)
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 24


def test_scanner_finishes_applied_receipt_after_completion_write_fails_without_restart(identity, monkeypatch):
    task_id, public_id, payload = _original()
    still_running = _original("running")[0]
    calls = []
    complete = worker._mark_completed

    def extract(expense, **_):
        calls.append(expense.id)
        return _ocr_result()

    def fail_completion(*_args, **_kwargs):
        raise SQLAlchemyError("injected failure after committed OCR result")

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", extract)
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    monkeypatch.setattr(worker, "_mark_completed", fail_completion)
    with pytest.raises(SQLAlchemyError):
        worker.run_task(task_id, payload)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "running" and task.result_summary_json is not None
    monkeypatch.setattr(worker, "_mark_completed", complete)
    assert recovery.resume_due_ocr_tasks() == 1
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "completed" and task.public_id == public_id and task.recovery_attempts == 0
        assert db.get(BackgroundTask, still_running).status == "running"
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 1
    assert calls == [payload["expense_id"]]


@pytest.mark.parametrize("interrupted_phase", ["queued", "running"])
def test_owned_scanner_continues_original_without_client_replay(identity, monkeypatch, clock, interrupted_phase):
    task_id, public_id, payload = _original(interrupted_phase)
    calls, finished = [], Event()

    def extract(expense, **_):
        calls.append(expense.id)
        return _ocr_result()

    def execute(identifier, original, *, registry, runner):
        assert identifier == task_id and original == payload
        runner(identifier, original, registry)
        finished.set()

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", extract)
    monkeypatch.setattr(_enrich, "_try_stage_thumbnail", lambda *_: None)
    monkeypatch.setattr(executor, "submit_task", execute)
    recovery.recover_orphaned_tasks()
    if interrupted_phase == "running":
        assert recovery.resume_due_ocr_tasks() == 0
        with SessionLocal() as db:
            assert worker.claim_queued_task(db, task_id) is None
        clock[0] += timedelta(seconds=11)
    monkeypatch.delenv("XPJ_BACKGROUND_TASK_INLINE", raising=False)
    scanner = recovery.start_ocr_task_recovery()
    try:
        assert finished.wait(5), "The owned scanner did not discover accepted work"
    finally:
        scanner.stop()
    assert not scanner.thread.is_alive()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "completed" and task.public_id == public_id
        assert json.loads(task.input_payload_json) == payload
        assert task.recovery_attempts == (1 if interrupted_phase == "running" else 0)
        assert db.get(Expense, payload["expense_id"]).amount_cents == 1990
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 1
        assert db.scalar(select(func.count()).select_from(BackgroundTask)) == 1
    assert calls == [payload["expense_id"]]


@pytest.mark.parametrize("code", ["ocr_timeout", "ocr_worker_exited"])
def test_backoff_keeps_quota_and_repeated_runtime_failure_stops(client, identity, monkeypatch, clock, code):
    task_id, public_id, payload = _original()
    calls = []

    def fail(*_, **__):
        calls.append(task_id)
        raise AppError(code, status_code=503)

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", fail)
    monkeypatch.setattr(executor, "submit_task", lambda identifier, original, *, registry, runner: runner(identifier, original, registry))
    settings = replace(admission.get_settings(), background_task_max_active=1)
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    worker.run_task(task_id, payload)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert (task.status, task.error_code, task.recovery_attempts) == ("queued", code, 1)
        assert task.recovery_after > clock[0] and task.result_summary_json is None
        with pytest.raises(admission.BackgroundTaskCapacityFullError):
            admission.stage_queued_task(db, task_type="csv_import", ledger_id="owner", initiator_account_id=None,
                initiator_device_id=None, progress_total=1)
        db.rollback()
        for _ in range(3):
            resume_pending_expense_enrichment(db, task_public_id=public_id, expense_id=payload["expense_id"], tenant_id="owner")
    recovery.recover_orphaned_tasks()
    assert recovery.resume_due_ocr_tasks() == 0 and calls == [task_id]
    response = client.get(f"/api/tasks/{public_id}", headers=identity.app_headers)
    assert response.status_code == 200 and response.json()["status"] == "queued"
    assert "稍后自动继续" in response.json()["progress_message"]
    clock[0] += timedelta(seconds=11)
    recovery.resume_due_ocr_tasks()
    clock[0] += timedelta(hours=1)
    recovery.recover_orphaned_tasks()
    assert recovery.resume_due_ocr_tasks() == 0
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert (task.status, task.error_code, task.recovery_attempts) == ("failed", code, 1)
        history = json.loads(task.recovery_history_json)
        assert len(history) == 1 and history[0]["error_code"] == code
        assert json.loads(task.input_payload_json) == payload and task.result_summary_json is None
    assert calls == [task_id, task_id]


def test_changed_recipe_retains_the_original_attempt_and_observed_success(identity, monkeypatch, clock, tmp_path):
    import hashlib

    from app import config
    from app.services import ocr_worker_client

    task_id, public_id, payload = _original()
    recipe = tmp_path / "recipe.json"
    recipe.write_text('{"name":"before-restart"}', encoding="utf-8")
    original_digest = hashlib.sha256(recipe.read_bytes()).hexdigest()
    monkeypatch.setattr(ocr_worker_client, "_runtime_command", lambda: ["worker", "--recipe", str(recipe)])
    settings = replace(config.get_settings(), ocr_provider="rapidocr", ocr_fallback_provider="local_llm")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    observed = []

    def extract(expense, **_):
        with SessionLocal() as db:
            observed.append(json.loads(getattr(db.get(BackgroundTask, task_id), "execution_context_json", "null")))
        if len(observed) == 1:
            raise AppError("ocr_timeout", status_code=503)
        extraction = _ocr_result().extractions[0]
        evidence = {"input_sha256": expense.image_hash, "identity": {"recipe_name": "actually-loaded",
            "recipe_sha256": "f" * 64}, "blocks": []}
        return replace(_ocr_result(), extractions=(replace(extraction, provider_name="rapidocr",
            result=replace(extraction.result, evidence=evidence)),))

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", extract)
    worker.run_task(task_id, payload)
    assert observed[0] is not None, "the interrupted attempt must have a committed identity before inference"
    recipe.write_text('{"name":"after-restart"}', encoding="utf-8")
    clock[0] += timedelta(seconds=11)
    worker.run_task(task_id, payload)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        previous = json.loads(task.recovery_history_json)[0]["execution_context"]
        current = json.loads(task.execution_context_json)
        assert previous == observed[0] and previous["configured"]["rapidocr"]["recipe_sha256"] == original_digest
        assert current["configured"]["rapidocr"]["recipe_sha256"] == hashlib.sha256(recipe.read_bytes()).hexdigest()
        assert current["observed"][0]["identity"]["recipe_name"] == "actually-loaded"
        assert current["observed"][0]["identity"]["recipe_sha256"] == "f" * 64
        assert "observed" not in previous and previous["attempt"] == 1 and current["attempt"] == 2
        assert (task.status, task.public_id, task.recovery_attempts) == ("completed", public_id, 1)
        assert json.loads(task.input_payload_json) == payload
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 1


@pytest.mark.parametrize("code", ["ocr_model_missing", "ocr_runtime_unavailable", "image_integrity_mismatch", "ocr_inference_failed"])
def test_nontransient_input_or_installation_failure_does_not_loop(identity, monkeypatch, code):
    task_id, _public_id, payload = _original()

    def fail(*_, **__):
        raise AppError(code, status_code=503)

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", fail)
    worker.run_task(task_id, payload)
    recovery.recover_orphaned_tasks()
    assert recovery.resume_due_ocr_tasks() == 0
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert (task.status, task.error_code, task.recovery_attempts) == ("failed", code, 0)
        assert task.result_summary_json is None and task.recovery_after is None


def test_repeated_process_death_cannot_reset_the_original_budget(identity, clock):
    task_id, _public_id, payload = _original("running")
    for attempt in range(4):
        recovery.recover_orphaned_tasks()
        with SessionLocal() as db:
            task = db.get(BackgroundTask, task_id)
            if attempt == 3:
                assert task.status == "failed" and task.recovery_attempts == 3
                assert len(json.loads(task.recovery_history_json)) == 3
                assert json.loads(task.input_payload_json) == payload
                break
            assert task.status == "queued" and task.recovery_attempts == attempt + 1
            clock[0] = task.recovery_after + timedelta(seconds=1)
            assert worker.claim_queued_task(db, task_id) is not None
    assert recovery.resume_due_ocr_tasks() == 0


@pytest.mark.parametrize("change,outcome", [("role", "permission_denied"), ("edited", "conflict"),
    ("confirmed", "not_pending"), ("cancelled", "cancelled")])
def test_recovered_original_checks_authority_before_inference(identity, monkeypatch, change, outcome):
    task_id, _public_id, payload = _original()
    with SessionLocal() as db:
        resolve_write_capability(db)
        task, expense = db.get(BackgroundTask, task_id), db.get(Expense, payload["expense_id"])
        if change == "role":
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
                LedgerMember.account_id == task.initiated_by_account_id))
            member.role = "viewer"
        elif change == "cancelled":
            task.cancellation_requested_at = now_utc()
        else:
            expense.merchant = "用户已核对"
            if change == "confirmed":
                expense.status = "confirmed"
            bump_row_version(expense)
        db.commit()
    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", lambda *_args, **_kwargs: pytest.fail("Obsolete or unauthorized OCR started"))
    monkeypatch.setattr(executor, "submit_task", lambda identifier, original, *, registry, runner: runner(identifier, original, registry))
    recovery.recover_orphaned_tasks()
    recovery.resume_due_ocr_tasks()
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        if outcome == "permission_denied":
            assert task.status == "failed" and task.error_code == outcome
        elif outcome == "cancelled":
            assert task.status == "cancelled"
        else:
            assert task.status == "completed" and json.loads(task.result_summary_json)["outcome"] == outcome
            assert db.get(Expense, payload["expense_id"]).merchant == "用户已核对"
        assert db.scalar(select(func.count()).select_from(OcrFact)) == 0


def test_cancellation_during_backoff_releases_quota_without_waiting_for_a_worker(client, identity, monkeypatch, clock):
    task_id, public_id, payload = _original()

    def fail(*_, **__):
        raise AppError("ocr_timeout", status_code=503)

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", fail)
    worker.run_task(task_id, payload)
    settings = replace(admission.get_settings(), background_task_max_active=1)
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    response = client.post(f"/api/tasks/{public_id}/cancel", headers=identity.app_headers)
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert client.post(f"/api/tasks/{public_id}/cancel", headers=identity.app_headers).json() == response.json()
    clock[0] += timedelta(hours=1)
    assert recovery.resume_due_ocr_tasks() == 0
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "cancelled" and task.recovery_after is None
        assert task.recovery_attempts == 1 and json.loads(task.input_payload_json) == payload
        admitted = admission.stage_queued_task(db, task_type="csv_import", ledger_id="owner",
            initiator_account_id=None, initiator_device_id=None, progress_total=1)
        assert admitted.status == "queued"


def test_cancellation_during_a_failing_inference_wins_over_automatic_recovery(client, identity, monkeypatch):
    task_id, public_id, payload = _original()

    def fail_after_cancellation(*_, **__):
        response = client.post(f"/api/tasks/{public_id}/cancel", headers=identity.app_headers)
        assert response.status_code == 200 and response.json()["cancellation_requested_at"] is not None
        raise AppError("ocr_timeout", status_code=503)

    monkeypatch.setattr(_enrich, "collect_auto_ocr_extractions", fail_after_cancellation)
    worker.run_task(task_id, payload)
    with SessionLocal() as db:
        task = db.get(BackgroundTask, task_id)
        assert task.status == "cancelled" and task.recovery_attempts == 0
        assert task.result_summary_json is None and task.recovery_after is None
        assert db.get(Expense, payload["expense_id"]).row_version == payload["expected_row_version"]
    assert recovery.resume_due_ocr_tasks() == 0
