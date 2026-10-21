"""Durable OCR rows wait before pool submission, leaving non-OCR capacity."""

from __future__ import annotations

import threading
import time

import pytest

from app.database import SessionLocal
from app.models import BackgroundTask
from app.services.background_task_executor import _ExecutorPool
from app.services.background_task_registry import TaskHandlerRegistry
from app.services.background_task_worker import run_task

pytestmark = pytest.mark.real_db


def test_waiting_ocr_does_not_occupy_non_ocr_worker(identity, monkeypatch):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "0")
    release = threading.Event()
    started = threading.Event()
    other_finished = threading.Event()
    calls = []

    def ocr(db, task, payload):
        calls.append(task.id)
        db.rollback()
        started.set()
        assert release.wait(timeout=10)

    def other(db, task, payload):
        other_finished.set()

    registry = TaskHandlerRegistry({"expense_enrichment": ocr, "expense_ocr_retry": ocr, "other": other})
    with SessionLocal() as db:
        tasks = [BackgroundTask(task_type=kind, status="queued")
                 for kind in ("expense_enrichment", "expense_ocr_retry", "other")]
        db.add_all(tasks)
        db.commit()
        ids = [task.id for task in tasks]
    pool = _ExecutorPool()
    try:
        pool.submit(ids[0], {}, registry, run_task)
        assert started.wait(timeout=5)
        pool.submit(ids[1], {}, registry, run_task)
        pool.submit(ids[1], {}, registry, run_task)  # Receipt replay is only another wakeup.
        pool.submit(ids[2], {}, registry, run_task)
        assert other_finished.wait(timeout=5), "A waiting OCR consumed the second thread"
        with SessionLocal() as db:
            assert db.get(BackgroundTask, ids[0]).status == "running"
            assert db.get(BackgroundTask, ids[1]).status == "queued"
            assert db.get(BackgroundTask, ids[1]).started_at is None
        assert calls == ids[:1]
    finally:
        release.set()
        # Wait for both accepted OCR wakeups, then join before DB fixture teardown.
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with SessionLocal() as db:
                    if all(db.get(BackgroundTask, task_id).status == "completed" for task_id in ids):
                        break
                time.sleep(0.01)
            else:
                raise AssertionError("accepted tasks did not complete")
        finally:
            pool.shutdown(wait=True)
    assert calls == ids[:2]


def test_nonwaiting_stop_requires_old_owner_exit_before_restart(identity, monkeypatch):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "0")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    registry = TaskHandlerRegistry()
    with SessionLocal() as db:
        tasks = [BackgroundTask(task_type="other", status="queued") for _ in range(2)]
        db.add_all(tasks)
        db.commit()
        ids = [task.id for task in tasks]

    def runner(task_id, payload, registry):
        if task_id == ids[0]:
            entered.set()
            assert release.wait(timeout=10)
        else:
            finished.set()

    pool = _ExecutorPool()
    try:
        pool.submit(ids[0], {}, registry, runner)
        assert entered.wait(timeout=5)
        pool.shutdown(wait=False)
        with pytest.raises(RuntimeError, match="previous background executor"):
            pool.start()
        with pytest.raises(RuntimeError, match="stopping"):
            pool.submit(ids[1], {}, registry, runner)
        release.set()
        deadline = time.monotonic() + 5
        while pool._active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not pool._active
        # A late callback must not reopen the stopped application by itself.
        with pytest.raises(RuntimeError, match="stopping"):
            pool.submit(ids[1], {}, registry, runner)
        pool.start()
        pool.submit(ids[1], {}, registry, runner)
        assert finished.wait(timeout=5)
    finally:
        release.set()
        pool.shutdown(wait=True)
