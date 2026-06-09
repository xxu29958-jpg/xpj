"""app_meta_service tests — schema-version defaults + binary-compatibility gate.

Covers the surviving startup-critical app_meta helpers: the version-tuple
compare, fresh-DB seeding, and the lifespan binary↔DB compatibility gate.

These moved here when the v0→v1 cut-over machinery was retired (the
``v1_migration`` handler and ``mark_v1_cut_over_completed`` were removed); the
gate and version helpers they were originally filed under live on.
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.services import app_meta_service
from app.services.app_meta_service import _version_tuple
from app.version import BACKEND_VERSION
from tests._infra.db import reset_db_state


@pytest.fixture(autouse=True)
def _fresh_db():
    """Force a fresh schema each test so app_meta seeding starts clean and
    prior-test state (e.g. a schema_min_compatible bump) doesn't bleed across."""
    reset_db_state()


# --- version_tuple --------------------------------------------------------


def test_version_tuple_compare_zero_nine_lt_one_oh() -> None:
    assert _version_tuple("0.9.0a1") < _version_tuple("1.0")
    assert _version_tuple("0.9") < _version_tuple("1.0")


# --- schema_version defaults ----------------------------------------------


def test_fresh_schema_version_is_seeded_to_backend_version() -> None:
    with SessionLocal() as db:
        assert app_meta_service.schema_version(db) == BACKEND_VERSION
        assert app_meta_service.schema_min_compatible(db) == BACKEND_VERSION


# --- binary compatibility gate --------------------------------------------


def test_binary_compatible_with_default_db() -> None:
    """Fresh DB (no app_meta rows) is treated as 0.9 → 0.9.0a1 OK."""
    with SessionLocal() as db:
        app_meta_service.assert_binary_compatible_with_db(db)  # must not raise


def test_binary_rejected_when_db_locked_to_v1_one_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the DB records a higher schema_min_compatible than the running
    binary, the binary must refuse to mount the DB. The live binary is well
    past 1.0, so simulate a pre-v1 binary by patching BACKEND_VERSION."""
    monkeypatch.setattr(app_meta_service, "BACKEND_VERSION", "0.9.0a1")
    with SessionLocal() as db:
        app_meta_service.set_value(db, "schema_min_compatible", "1.0")

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        app_meta_service.assert_binary_compatible_with_db(db)
    assert exc.value.error == "backend_version_too_old"
