"""Cloud-safe claim tests for background_tasks runners."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.log_sanitize import SanitizedFormatter
from app.models import BackgroundTask
from app.services import background_task_executor, background_task_service, background_task_worker
from app.services.background_task_registry import TaskHandlerRegistry

pytestmark = pytest.mark.real_db


def test_claim_queued_task_is_db_atomic(*, identity) -> None:
    with SessionLocal() as db:
        task = BackgroundTask(task_type="test_claim_once", status="queued")
        db.add(task)
        db.commit()
        task_id = task.id

    with SessionLocal() as db:
        claimed = background_task_worker.claim_queued_task(db, task_id)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.started_at is not None
    assert claimed.last_progress_at is not None

    with SessionLocal() as db:
        duplicate_claim = background_task_worker.claim_queued_task(db, task_id)

    assert duplicate_claim is None
    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        assert row.status == "running"


def test_run_task_does_not_execute_already_claimed_row(*, identity) -> None:
    ran = False

    def handler(_db, _task, _payload):
        nonlocal ran
        ran = True

    with SessionLocal() as db:
        task = BackgroundTask(task_type="test_already_claimed", status="running")
        db.add(task)
        db.commit()
        task_id = task.id

    registry = TaskHandlerRegistry({"test_already_claimed": handler})
    background_task_worker.run_task(task_id, {}, registry)

    assert ran is False
    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        assert row.status == "running"


@pytest.mark.parametrize("concurrent_status", ["queued", "running", "completed", "cancelled"])
def test_submission_refusal_cannot_overwrite_a_concurrent_task_outcome(monkeypatch, caplog, *, identity, concurrent_status) -> None:
    with SessionLocal() as db:
        task = BackgroundTask(task_type="test_replay_refusal", status="queued")
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        def race_then_refuse(*_args, **_kwargs):
            with SessionLocal() as worker_db:
                row = worker_db.get(BackgroundTask, task_id)
                row.status = concurrent_status
                row.result_summary_json = '{"original_worker":true}'
                worker_db.commit()
            assert task.status == "queued", "The request still holds its original stale task snapshot"
            raise RuntimeError("duplicate wakeup was not accepted")

        monkeypatch.setattr("app.services.background_task_executor.submit_task", race_then_refuse)
        with pytest.raises(background_task_service.BackgroundTaskSubmissionError):
            background_task_service.submit_existing(db, task, {})

    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        assert row.status == ("failed" if concurrent_status == "queued" else concurrent_status)
        assert row.error_code == ("task_submission_failed" if concurrent_status == "queued" else None)
        assert row.result_summary_json == '{"original_worker":true}'
    output = "\n".join(SanitizedFormatter().format(record) for record in caplog.records)
    assert f"background task {task_id} stage=submit" in output
    assert "RuntimeError" in output and "in race_then_refuse" in output


def test_claim_failure_is_observed_without_publishing_a_new_task_state(monkeypatch, caplog, *, identity):
    with SessionLocal() as db:
        task = BackgroundTask(task_type="test_unstarted_handler", status="queued")
        db.add(task)
        db.commit()
        task_id = task.id

    def unavailable_claim(*_args):
        raise SQLAlchemyError("token=synthetic-claim-secret")

    monkeypatch.setattr(background_task_worker, "claim_queued_task", unavailable_claim)
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "0")
    background_task_executor.submit_task(task_id, {}, registry=TaskHandlerRegistry(), runner=background_task_worker.run_task)
    background_task_executor.shutdown_executor(wait=True)
    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        assert row.status == "queued" and row.started_at is None and row.error_code is None
    output = "\n".join(SanitizedFormatter().format(record) for record in caplog.records)
    assert f"background task {task_id} stage=worker_boundary" in output
    assert "SQLAlchemyError" in output and "in unavailable_claim" in output
    assert "synthetic-claim-secret" not in output
