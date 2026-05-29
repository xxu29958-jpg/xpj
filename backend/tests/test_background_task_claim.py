"""Cloud-safe claim tests for background_tasks runners."""

from __future__ import annotations

from app.database import SessionLocal
from app.models import BackgroundTask
from app.services import background_task_service as bgtasks


def test_claim_queued_task_is_db_atomic(*, identity) -> None:
    with SessionLocal() as db:
        task = BackgroundTask(task_type="test_claim_once", status="queued")
        db.add(task)
        db.commit()
        task_id = task.id

    with SessionLocal() as db:
        claimed = bgtasks._claim_queued_task(db, task_id)

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.started_at is not None
    assert claimed.last_progress_at is not None

    with SessionLocal() as db:
        duplicate_claim = bgtasks._claim_queued_task(db, task_id)

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

    registry = bgtasks.TaskHandlerRegistry({"test_already_claimed": handler})
    bgtasks._run_task(task_id, {}, registry)

    assert ran is False
    with SessionLocal() as db:
        row = db.get(BackgroundTask, task_id)
        assert row.status == "running"
