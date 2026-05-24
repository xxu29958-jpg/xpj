"""ADR-0031 cut-over MVP tests."""

from __future__ import annotations

import os

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
    saved = bgtasks.get_registered_handlers()
    for k in list(saved.keys()):
        bgtasks._handlers.pop(k, None)
    try:
        yield
    finally:
        os.environ.pop("XPJ_BACKGROUND_TASK_INLINE", None)
        for k in list(bgtasks._handlers.keys()):
            bgtasks._handlers.pop(k, None)
        for k, h in saved.items():
            bgtasks.register_handler(k, h)


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
    when BACKEND_VERSION was 0.9.0a1; since the binary is now 1.0.0,
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
    With BACKEND_VERSION now at 1.0.0 the safety branch is dormant in
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


# --- mark_v1_cut_over_completed writes all three keys ---------------------


def test_mark_v1_cut_over_completed_writes_all_keys() -> None:
    with SessionLocal() as db:
        app_meta_service.mark_v1_cut_over_completed(db)

    with SessionLocal() as db:
        assert app_meta_service.schema_version(db) == V1_TARGET_VERSION
        assert app_meta_service.schema_min_compatible(db) == V1_TARGET_VERSION
        assert app_meta_service.migration_completed_at(db) is not None
