"""Durable OCR rows wait before pool submission, leaving non-OCR capacity."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from app.database import SessionLocal
from app.log_sanitize import SanitizedFormatter
from app.models import BackgroundTask
from app.services import background_task_executor as executor
from app.services.background_task_executor import _ExecutorPool
from app.services.background_task_registry import TaskHandlerRegistry
from app.services.background_task_worker import run_task
from app.services.time_service import now_utc

pytestmark = pytest.mark.real_db


def _wait_completed(task_ids: list[int]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if all(db.get(BackgroundTask, task_id).status == "completed" for task_id in task_ids):
                return
        time.sleep(0.01)
    raise AssertionError("accepted tasks did not complete")


@pytest.mark.parametrize("waiting, expected", [
    ([("expense_enrichment", 2, "owner", 0), ("expense_ocr_retry", 1, "owner", 0)], [2, 1]),
    ([("expense_enrichment", 1, "owner", 61), ("expense_ocr_retry", 2, "owner", 0)], [1, 2]),
    ([("expense_enrichment", 1, "owner", 61), ("expense_ocr_retry", 2, "owner", 60)], [1, 2]),
    ([("expense_ocr_retry", 1, "owner", 0), ("expense_ocr_retry", 2, "owner", 0)], [2, 1]),
    ([("expense_enrichment", 1, "owner", 0), ("expense_enrichment", 2, "owner", 0)], [2, 1]),
    ([("expense_enrichment", 1, "owner", 0), ("expense_enrichment", 1, "another", 0)], [2, 1]),
], ids=["interactive", "aging", "aged-oldest-first", "interactive-member", "upload-member", "ledger"])
def test_ocr_next_slot_uses_server_intent_age_and_actor(identity, monkeypatch, waiting, expected):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "0")
    instant = now_utc()
    monkeypatch.setattr(executor, "now_utc", lambda: instant)
    entered, release, calls = threading.Event(), threading.Event(), []
    with SessionLocal() as db:
        tasks = [BackgroundTask(task_type=kind, initiated_by_account_id=actor, tenant_id=ledger,
            created_at=instant - timedelta(seconds=age))
            for kind, actor, ledger, age in [("expense_enrichment", 1, "owner", 0), *waiting]]
        db.add_all(tasks)
        db.commit()
        ids = [task.id for task in tasks]

    def handler(db, task, payload):
        calls.append(task.id)
        db.rollback()
        if task.id == ids[0]:
            entered.set()
            assert release.wait(timeout=10)

    registry = TaskHandlerRegistry({"expense_enrichment": handler, "expense_ocr_retry": handler})
    pool = _ExecutorPool()
    try:
        pool.submit(ids[0], {}, registry, run_task)
        assert entered.wait(timeout=5)
        # Client-like payload claims cannot change the durable server task's class/actor.
        forged = {"priority": "interactive", "task_type": "expense_ocr_retry", "initiated_by_account_id": 999}
        pool.submit(ids[1], forged, registry, run_task)
        pool.submit(ids[2], {}, registry, run_task)
        pool.submit(ids[1], forged, registry, run_task)
        with SessionLocal() as db:
            assert all(db.get(BackgroundTask, identifier).status == "queued" for identifier in ids[1:])
        assert calls == ids[:1], "The current inference was preempted or a second OCR started"
        release.set()
        _wait_completed(ids)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert calls == [ids[index] for index in [0, *expected]]


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
            _wait_completed(ids)
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


def test_callback_dispatch_refusal_keeps_queued_receipt_and_reports_failure(identity, monkeypatch, caplog):
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "0")
    entered, release = threading.Event(), threading.Event()

    def handler(db, task, payload):
        db.rollback()
        entered.set()
        assert release.wait(timeout=10)

    registry = TaskHandlerRegistry({"expense_enrichment": handler})
    with SessionLocal() as db:
        tasks = [BackgroundTask(task_type="expense_enrichment", status="queued") for _ in range(2)]
        db.add_all(tasks)
        db.commit()
        first, waiting = [task.id for task in tasks]
    pool = _ExecutorPool()
    try:
        pool.submit(first, {}, registry, run_task)
        assert entered.wait(timeout=5)
        pool.submit(waiting, {}, registry, run_task)

        def refuse(*_args, **_kwargs):
            raise RuntimeError("token=synthetic-dispatch-secret")

        monkeypatch.setattr(pool._executor, "submit", refuse)
        release.set()
        deadline = time.monotonic() + 5
        while not any("stage=dispatch" in row.getMessage() for row in caplog.records):
            assert time.monotonic() < deadline, "Callback failure had no reporting owner"
            time.sleep(0.01)
        with SessionLocal() as db:
            assert db.get(BackgroundTask, first).status == "completed"
            row = db.get(BackgroundTask, waiting)
            assert row.status == "queued" and row.started_at is None and row.error_code is None
        output = "\n".join(SanitizedFormatter().format(record) for record in caplog.records)
        assert "in refuse" in output and "synthetic-dispatch-secret" not in output
    finally:
        release.set()
        pool.shutdown(wait=True)
