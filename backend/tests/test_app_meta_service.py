"""Dataset compatibility and non-authoritative app metadata tests.

Covers the surviving startup-critical app_meta helpers: structured version
comparison, Alembic-owned fresh metadata, and the binary↔DB compatibility gate.

These moved here when the v0→v1 cut-over machinery was retired (the
``v1_migration`` handler and ``mark_v1_cut_over_completed`` were removed); the
gate and version helpers they were originally filed under live on.
"""

from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.errors import AppError
from app.models import DatasetAuthorityRecord
from app.services import app_meta_service
from app.services.app_meta_service import _version_tuple
from app.version import BACKEND_VERSION
from tests._infra.db import reset_db_state

pytestmark = pytest.mark.real_db


@pytest.fixture(autouse=True)
def _fresh_db():
    """Force a fresh schema each test so Alembic metadata starts clean and
    prior-test state (e.g. a schema_min_compatible bump) doesn't bleed across."""
    reset_db_state()


# --- version_tuple --------------------------------------------------------


def test_version_tuple_compare_zero_nine_lt_one_oh() -> None:
    assert _version_tuple("0.9.0a1") < _version_tuple("1.0")
    assert _version_tuple("0.9") < _version_tuple("1.0")
    assert _version_tuple("1.2.0-alpha.2") < _version_tuple("1.2.0-alpha.10")
    assert _version_tuple("1.2.0-alpha.10") < _version_tuple("1.2.0-beta.1")
    assert _version_tuple("1.2.0-beta.1") < _version_tuple("1.2.0-rc.1")
    assert _version_tuple("1.2.0-rc.1") < _version_tuple("1.2.0")
    assert _version_tuple("1.2.0") < _version_tuple("1.2.1-alpha.1")


# --- dataset compatibility authority --------------------------------------


def test_fresh_schema_minimum_is_owned_by_dataset_authority() -> None:
    with SessionLocal() as db:
        assert app_meta_service.schema_min_compatible(db) == BACKEND_VERSION


def test_legacy_dataset_keys_cannot_be_reintroduced_through_app_meta() -> None:
    with SessionLocal() as db, pytest.raises(AppError) as excinfo:
        app_meta_service.set_value(db, "server_id", "not-authoritative")
    assert excinfo.value.error == "dataset_authority_read_only"


# --- binary compatibility gate --------------------------------------------


def test_binary_compatible_with_default_db() -> None:
    """Fresh DB (no app_meta rows) is treated as 0.9 → 0.9.0a1 OK."""
    with SessionLocal() as db:
        app_meta_service.assert_binary_compatible_with_db(db)  # must not raise


def test_binary_rejected_when_db_locked_to_v1_one_higher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compatibility refusal occurs before backup, Alembic, or seed writes."""
    monkeypatch.setattr(app_meta_service, "BACKEND_VERSION", "0.9.0a1")
    with SessionLocal() as db:
        authority = db.get(DatasetAuthorityRecord, 1)
        assert authority is not None
        authority.schema_min_compatible = "1.3.0"
        db.commit()

    with SessionLocal() as db, pytest.raises(AppError) as exc:
        app_meta_service.assert_binary_compatible_with_db(db)
    assert exc.value.error == "backend_version_too_old"
