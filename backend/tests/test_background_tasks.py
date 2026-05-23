"""ADR-0030 PR-1: background_tasks executor + service + API.

Tests use inline mode (``XPJ_BACKGROUND_TASK_INLINE=1``) to run handlers
synchronously on the test thread, so we can verify chunked progress /
cancellation / completion without a real ThreadPoolExecutor + a file-
backed SQLite shared across threads.

One test (``test_orphan_recovery_force_fails_stale_running``) directly
manipulates row state to simulate "process died mid-task" without going
through enqueue, so it doesn't depend on inline mode.
"""

from __future__ import annotations

import json
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Account, BackgroundTask
from app.services import background_task_service as bgtasks
from app.services.time_service import now_utc


def _owner_account_id() -> int:
    with SessionLocal() as db:
        owner = db.query(Account).order_by(Account.id.asc()).first()
        assert owner is not None
        return owner.id


@pytest.fixture(autouse=True)
def _inline_handlers():
    """Each test runs handlers inline + starts with an empty handler
    registry, so registration leakage between tests can't happen."""
    os.environ["XPJ_BACKGROUND_TASK_INLINE"] = "1"
    saved = bgtasks.get_registered_handlers()
    # bgtasks._handlers is private; reset via re-registering an empty dict
    for key in list(saved.keys()):
        bgtasks._handlers.pop(key, None)
    try:
        yield
    finally:
        os.environ.pop("XPJ_BACKGROUND_TASK_INLINE", None)
        for key in list(bgtasks._handlers.keys()):
            bgtasks._handlers.pop(key, None)
        for key, handler in saved.items():
            bgtasks.register_handler(key, handler)


# --- handler dispatch --------------------------------------------------


def test_enqueue_runs_handler_and_marks_completed(*, identity) -> None:
    captured: dict[str, str] = {}

    def handler(db, task, payload):
        captured["task_id"] = task.public_id
        captured["payload_echo"] = payload.get("echo", "")
        task.result_summary_json = json.dumps({"ran": True})
        db.commit()

    bgtasks.register_handler("test_echo", handler)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_echo",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
            payload={"echo": "hello"},
        )
        public_id = task.public_id

    assert captured["payload_echo"] == "hello"
    with SessionLocal() as db:
        row = bgtasks.get_task(db, public_id, account_id=_owner_account_id())
        assert row.status == "completed"
        assert row.completed_at is not None
        assert json.loads(row.result_summary_json)["ran"] is True


def test_enqueue_unknown_task_type_400(*, identity) -> None:
    from app.errors import AppError

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bgtasks.enqueue(
            db,
            task_type="not_registered",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
    assert exc.value.error == "unknown_task_type"


def test_handler_exception_marks_failed(*, identity) -> None:
    def boom(db, task, payload):
        raise RuntimeError("kaboom")

    bgtasks.register_handler("test_boom", boom)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_boom",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
        public_id = task.public_id

    with SessionLocal() as db:
        row = bgtasks.get_task(db, public_id, account_id=_owner_account_id())
        assert row.status == "failed"
        assert row.error_code == "RuntimeError"
        assert "kaboom" in (row.error_message or "")


# --- chunked progress + cancellation ----------------------------------


def test_handler_reports_progress_through_chunks(*, identity) -> None:
    def chunked(db, task, payload):
        total = 5
        for i in range(total):
            bgtasks.update_progress(
                db, task.id, current=i + 1, total=total, message=f"row {i + 1}"
            )

    bgtasks.register_handler("test_chunked", chunked)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_chunked",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
            progress_total=5,
        )
        public_id = task.public_id

    with SessionLocal() as db:
        row = bgtasks.get_task(db, public_id, account_id=_owner_account_id())
        assert row.status == "completed"
        assert row.progress_current == 5
        assert row.progress_total == 5
        assert row.progress_message == "row 5"
        assert row.last_progress_at is not None


def test_handler_observes_cancellation_request(*, identity) -> None:
    def cancellable(db, task, payload):
        # Pre-set cancellation BEFORE the chunk loop so the inline path
        # observes it at the first check.
        with SessionLocal() as outer:
            outer_row = outer.get(BackgroundTask, task.id)
            outer_row.cancellation_requested_at = now_utc()
            outer.commit()
        # Now the inline handler observes the flag on its first chunk.
        for i in range(10):
            if bgtasks.check_cancellation_requested(db, task.id):
                raise bgtasks.TaskCancelledError()
            bgtasks.update_progress(db, task.id, current=i + 1, total=10)
        # If we somehow get here without cancelling, fail the test.
        raise AssertionError("Cancellation flag should have stopped the loop")

    bgtasks.register_handler("test_cancellable", cancellable)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_cancellable",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
            progress_total=10,
        )
        public_id = task.public_id

    with SessionLocal() as db:
        row = bgtasks.get_task(db, public_id, account_id=_owner_account_id())
        assert row.status == "cancelled"
        assert row.completed_at is not None


def test_request_cancellation_idempotent_on_terminal_task(*, identity) -> None:
    """Cancelling a completed task is a no-op (returns row unchanged)."""

    def finishes_immediately(db, task, payload):
        return  # nothing to do

    bgtasks.register_handler("test_immediate", finishes_immediately)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_immediate",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
        public_id = task.public_id

    with SessionLocal() as db:
        # cancel should not flip status from completed
        row = bgtasks.request_cancellation(db, public_id, account_id=_owner_account_id())
        assert row.status == "completed"
        assert row.cancellation_requested_at is None


# --- account isolation ------------------------------------------------


def test_account_isolation_get(*, identity) -> None:
    bgtasks.register_handler("test_iso", lambda db, t, p: None)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_iso",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
        public_id = task.public_id

    # Wrong account is told 'not found' (no existence leak).
    from app.errors import AppError

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        bgtasks.get_task(db, public_id, account_id=99999)
    assert exc.value.error == "task_not_found"


def test_list_recent_tasks_account_scoped(*, identity) -> None:
    bgtasks.register_handler("test_iso2", lambda db, t, p: None)
    with SessionLocal() as db:
        bgtasks.enqueue(
            db,
            task_type="test_iso2",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
        # Same enqueue but a different account; should not appear in mine.
        bgtasks.enqueue(
            db,
            task_type="test_iso2",
            initiator_account_id=99999,
            ledger_id="owner",
        )

    with SessionLocal() as db:
        mine = bgtasks.list_recent_tasks(db, account_id=_owner_account_id())
        assert len(mine) == 1
        assert mine[0].initiated_by_account_id == _owner_account_id()


# --- orphan recovery --------------------------------------------------


def test_orphan_recovery_force_fails_stale_running() -> None:
    """Simulate a backend crash: row is ``running`` but heartbeat is
    older than 5 minutes. recover_orphaned_tasks() should force-fail it."""
    with SessionLocal() as db:
        stale = BackgroundTask(
            task_type="test_orphan",
            status="running",
            last_progress_at=now_utc() - timedelta(minutes=10),
            started_at=now_utc() - timedelta(minutes=11),
        )
        db.add(stale)
        db.commit()
        stale_id = stale.id

    recovered = bgtasks.recover_orphaned_tasks()
    assert recovered >= 1

    with SessionLocal() as db:
        row = db.get(BackgroundTask, stale_id)
        assert row.status == "failed"
        assert row.error_code == "orphaned_after_restart"


def test_orphan_recovery_leaves_fresh_running_alone() -> None:
    """A ``running`` row with a recent heartbeat is not touched."""
    with SessionLocal() as db:
        fresh = BackgroundTask(
            task_type="test_fresh",
            status="running",
            last_progress_at=now_utc(),
            started_at=now_utc() - timedelta(seconds=10),
        )
        db.add(fresh)
        db.commit()
        fresh_id = fresh.id

    bgtasks.recover_orphaned_tasks()

    with SessionLocal() as db:
        row = db.get(BackgroundTask, fresh_id)
        assert row.status == "running"


# --- API surface ------------------------------------------------------


def test_api_get_returns_task(client: TestClient, *, identity) -> None:
    bgtasks.register_handler("test_api", lambda db, t, p: None)
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type="test_api",
            initiator_account_id=_owner_account_id(),
            ledger_id="owner",
        )
        public_id = task.public_id

    response = client.get(f"/api/tasks/{public_id}", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["public_id"] == public_id
    assert body["task_type"] == "test_api"
    assert body["status"] == "completed"


def test_api_list_returns_recent(client: TestClient, *, identity) -> None:
    bgtasks.register_handler("test_list", lambda db, t, p: None)
    with SessionLocal() as db:
        for _ in range(3):
            bgtasks.enqueue(
                db,
                task_type="test_list",
                initiator_account_id=_owner_account_id(),
                ledger_id="owner",
            )

    response = client.get("/api/tasks", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert len(body["items"]) == 3


def test_api_get_unknown_id_404(client: TestClient, *, identity) -> None:
    response = client.get("/api/tasks/not-a-real-uuid", headers=identity.app_headers)
    assert response.status_code == 404


def test_api_cancel_sets_flag(client: TestClient, *, identity) -> None:
    """Test the API surface — the actual cancellation observation by the
    handler is covered by the handler-level test above."""

    def slow(db, task, payload):
        # Don't observe cancellation here; we just want the API to set the
        # flag and the row to reflect it. We mark the task running and
        # return without touching status — service marks it completed.
        return

    bgtasks.register_handler("test_cancel_api", slow)
    with SessionLocal() as db:
        # Manually leave one task queued via DB direct so cancel has
        # something non-terminal to flip.
        queued = BackgroundTask(
            task_type="test_cancel_api",
            status="queued",
            initiated_by_account_id=_owner_account_id(),
            tenant_id="owner",
        )
        db.add(queued)
        db.commit()
        public_id = queued.public_id

    response = client.post(f"/api/tasks/{public_id}/cancel", headers=identity.app_headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["cancellation_requested_at"] is not None
