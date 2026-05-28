"""ADR-0031 cut-over MVP tests."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.models import BackgroundTask
from app.services import (
    app_meta_service,
    v1_migration_service,
)
from app.services import (
    background_task_service as bgtasks,
)
from app.services.app_meta_service import (
    V09_DEFAULT_VERSION,
    V1_TARGET_VERSION,
    _version_tuple,
)
from app.services.time_service import now_utc
from tests._infra.db import reset_db_state


@pytest.fixture(autouse=True)
def _fresh_db():
    """app_meta table is brand new; force a fresh schema each test so the
    table exists and previous-test state doesn't bleed across (e.g. a
    test that set schema_min_compatible=1.0 would break the next test's
    binary compatibility assertion)."""
    reset_db_state()


@pytest.fixture(autouse=True)
def _inline_handlers():
    """Run background tasks synchronously; clean registry between tests."""
    os.environ["XPJ_BACKGROUND_TASK_INLINE"] = "1"
    saved = bgtasks.replace_registered_handlers_for_testing()
    try:
        yield
    finally:
        os.environ.pop("XPJ_BACKGROUND_TASK_INLINE", None)
        bgtasks.replace_registered_handlers_for_testing(saved)


# --- version_tuple --------------------------------------------------------


def test_version_tuple_compare_zero_nine_lt_one_oh() -> None:
    assert _version_tuple("0.9.0a1") < _version_tuple("1.0")
    assert _version_tuple("0.9") < _version_tuple("1.0")


# --- schema_version defaults ----------------------------------------------


def test_default_schema_version_is_zero_nine() -> None:
    with SessionLocal() as db:
        assert app_meta_service.schema_version(db) == V09_DEFAULT_VERSION
        assert app_meta_service.schema_min_compatible(db) == V09_DEFAULT_VERSION


# --- binary compatibility gate --------------------------------------------


def test_binary_compatible_with_default_db() -> None:
    """Fresh DB (no app_meta rows) is treated as 0.9 → 0.9.0a1 OK."""
    with SessionLocal() as db:
        app_meta_service.assert_binary_compatible_with_db(db)  # must not raise


def test_binary_rejected_when_db_locked_to_v1_one_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a future cut-over recorded a higher schema_min than the running
    binary, the binary must refuse to mount the DB. Originally written
    when BACKEND_VERSION was 0.9.0a1; since the binary is now 1.2.0,
    simulate a pre-v1 binary by patching BACKEND_VERSION just for this
    test."""
    monkeypatch.setattr(app_meta_service, "BACKEND_VERSION", "0.9.0a1")
    with SessionLocal() as db:
        app_meta_service.set_value(db, "schema_min_compatible", "1.0")

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        app_meta_service.assert_binary_compatible_with_db(db)
    assert exc.value.error == "backend_version_too_old"


# --- cut-over handler refuse on pre-v1 binary -----------------------------


def test_v1_migration_handler_refuses_pre_v1_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cut-over from a 0.9.x binary would lock the DB out of its own
    process. Handler refuses; schema_version stays at 0.9.
    With BACKEND_VERSION now at 1.2.0 the safety branch is dormant in
    production; patch it back to 0.9.x to keep exercising the refuse path."""
    monkeypatch.setattr(v1_migration_service, "BACKEND_VERSION", "0.9.0a1")
    v1_migration_service.register()
    with SessionLocal() as db:
        task = bgtasks.enqueue(
            db,
            task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
            initiator_account_id=None,
            ledger_id=None,
        )
        public_id = task.public_id

    with SessionLocal() as db:
        row = db.query(BackgroundTask).filter(BackgroundTask.public_id == public_id).one()
        assert row.status == "failed"
        # Error message proves the safety branch fired.
        assert "Refuse to cut over" in (row.error_message or "")

        # schema_version was NOT updated.
        assert app_meta_service.schema_version(db) == V09_DEFAULT_VERSION
        assert app_meta_service.schema_min_compatible(db) == V09_DEFAULT_VERSION


def test_v1_migration_handler_observes_cancellation_before_backup() -> None:
    with SessionLocal() as db:
        task = BackgroundTask(
            task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
            status="running",
            cancellation_requested_at=now_utc(),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        with pytest.raises(bgtasks.TaskCancelledError):
            v1_migration_service._handler(db, task, {})

        assert app_meta_service.schema_version(db) == V09_DEFAULT_VERSION
        assert app_meta_service.schema_min_compatible(db) == V09_DEFAULT_VERSION


def test_v1_migration_handler_observes_cancellation_before_final_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        v1_migration_service.backup_service,
        "create_pre_v1_backup",
        lambda: SimpleNamespace(file_name="pre-v1-test.db", size_bytes=123),
    )
    monkeypatch.setattr(
        v1_migration_service.migration_readiness_service,
        "build_v1_migration_readiness_report",
        lambda *, create_backup=False: SimpleNamespace(ready=True, checks=[]),
    )
    original_update_progress = bgtasks.update_progress

    def cancel_after_snapshot_progress(db, task_id: int, **kwargs) -> None:
        original_update_progress(db, task_id, **kwargs)
        if kwargs.get("current") == 2:
            task = db.get(BackgroundTask, task_id)
            assert task is not None
            task.cancellation_requested_at = now_utc()
            db.commit()

    monkeypatch.setattr(bgtasks, "update_progress", cancel_after_snapshot_progress)

    with SessionLocal() as db:
        task = BackgroundTask(
            task_type=v1_migration_service.V1_MIGRATION_TASK_TYPE,
            status="running",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        with pytest.raises(bgtasks.TaskCancelledError):
            v1_migration_service._handler(db, task, {})

        assert app_meta_service.schema_version(db) == V09_DEFAULT_VERSION
        assert app_meta_service.schema_min_compatible(db) == V09_DEFAULT_VERSION


# --- mark_v1_cut_over_completed writes all three keys ---------------------


def test_mark_v1_cut_over_completed_writes_all_keys() -> None:
    with SessionLocal() as db:
        app_meta_service.mark_v1_cut_over_completed(db)

    with SessionLocal() as db:
        assert app_meta_service.schema_version(db) == V1_TARGET_VERSION
        assert app_meta_service.schema_min_compatible(db) == V1_TARGET_VERSION
        assert app_meta_service.migration_completed_at(db) is not None


def test_mark_v1_cut_over_completed_rolls_back_partial_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = app_meta_service._set_value_in_transaction
    calls = 0

    def fail_after_first_write(*args, **kwargs) -> None:
        nonlocal calls
        calls += 1
        original(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("simulated app_meta write failure")

    monkeypatch.setattr(
        app_meta_service,
        "_set_value_in_transaction",
        fail_after_first_write,
    )

    with SessionLocal() as db, pytest.raises(RuntimeError, match="simulated"):
        app_meta_service.mark_v1_cut_over_completed(db)

    with SessionLocal() as db:
        assert app_meta_service.schema_version(db) == V09_DEFAULT_VERSION
        assert app_meta_service.schema_min_compatible(db) == V09_DEFAULT_VERSION
        assert app_meta_service.migration_completed_at(db) is None
