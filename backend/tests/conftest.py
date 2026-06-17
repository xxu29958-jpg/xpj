"""Top-level pytest hooks and fixtures.

Implementation lives in ``tests/_infra/``:

- ``env``      — TEST_* path/token constants + ``os.environ`` wiring
- ``assets``   — static byte resources (PNG_BYTES, ...)
- ``identity`` — TestIdentity dataclass + seed_identity factory
- ``db``       — schema / data lifecycle (reset, cleanup)
- ``client``   — TestClient + dependency overrides

Tests import constants and the ``TestIdentity`` type directly from those
modules. This file only defines the fixtures and the session-end hook.
"""

from __future__ import annotations

import pytest

# Importing tests._infra.env sets os.environ before any app.* import.
from fastapi.testclient import TestClient

from tests._infra import env  # noqa: F401
from tests._infra.client import make_test_client
from tests._infra.db import (
    cleanup_runtime,
    reset_db_state,
    transactional_isolation,
)
from tests._infra.identity import TestIdentity, seed_identity


@pytest.fixture(scope="session", autouse=True)
def _isolation_schema():
    """Build schema + base seed ONCE for the session (PostgreSQL isolation lane).

    Per-test ``_db_isolation`` then wraps each test in a rolled-back transaction
    (or a full reset for ``@pytest.mark.real_db`` tests).
    """
    reset_db_state()
    yield


@pytest.fixture(autouse=True)
def _db_isolation(request: pytest.FixtureRequest):
    """Per-test DB lifecycle. Autouse so tests that touch the DB WITHOUT the
    ``identity`` fixture are isolated too — otherwise their ``SessionLocal()``
    stays bound to the engine and their commits leak into the shared DB.

    Wrap each test in a rolled-back outer transaction (schema already built once
    by ``_isolation_schema``). ``@pytest.mark.real_db`` opts out for tests needing
    real cross-connection commits (concurrency, ``engine.begin()`` migrations);
    they get a full reset + a teardown reset so their committed rows don't leak
    into the next transaction-isolated test's baseline.
    """
    if "real_db" in request.keywords:
        reset_db_state()
        try:
            yield
        finally:
            reset_db_state()
        return
    with transactional_isolation():
        yield


@pytest.fixture()
def identity(_db_isolation) -> TestIdentity:
    # _db_isolation already set up the per-test transaction (or real_db reset).
    return seed_identity()


@pytest.fixture()
def client(identity: TestIdentity):
    with make_test_client() as test_client:
        yield test_client


@pytest.fixture()
def web_client(client: TestClient) -> TestClient:
    """Bypass the /web loopback gate for tests (peer is 'testclient')."""
    from app.main import app
    from app.routes.web_app import _require_local as _web_require_local

    app.dependency_overrides[_web_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_web_require_local, None)


@pytest.fixture()
def external_upload_dir(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Point upload_dir at an external (outside-backend) path for the test."""
    from dataclasses import replace

    from app.services import file_service, thumb_service

    external = (tmp_path / "external-uploads").resolve()
    overridden = replace(file_service.get_settings(), upload_dir=external)
    monkeypatch.setattr(file_service, "get_settings", lambda: overridden)
    monkeypatch.setattr(thumb_service, "get_settings", lambda: overridden)
    return external


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_db: opt out of the PostgreSQL lane's per-test transaction-rollback "
        "isolation and run against a real committed DB (full reset_db_state). For "
        "tests that need real cross-connection commits — concurrency, true "
        "background-thread work.",
    )


# Tests that cannot run under the PostgreSQL lane's per-test transaction-rollback
# isolation, marked ``real_db`` centrally (one auditable place) instead of
# scattering ``@pytest.mark.real_db`` across the suite. Matched as substrings of
# ``item.nodeid`` (a trailing ``::`` pins a whole module; otherwise a test prefix).
_PG_REAL_DB_NODES = (
    # Schema/engine manipulation: drop_all / init_db / engine.begin / create_engine
    # / reset_db_state auto-commit DDL OUTSIDE the per-test transaction while the
    # re-seed lands in the rolled-back savepoint — so the committed baseline would
    # be destroyed for every later test. Must run against a real committed DB.
    "tests/test_ocr_facts_backfill_step3.py::",  # _backfill_legacy_raw_text via engine.begin
    "tests/test_app_meta_service.py::",  # reset_db_state (fresh-DB schema-version seeding)
    "tests/test_alembic_tag_migration.py::",  # alembic up/down round-trip via engine.begin DDL
    "tests/test_alembic_debt_idempotency_unique_migration.py::",  # alembic up/down round-trip via engine.begin DDL
    "tests/test_alembic_goal_debt_repayment_migration.py::",  # ADR-0049 §6 widen-goals alembic round-trip via engine.begin DDL
    "tests/test_alembic_goal_target_date_migration.py::",  # ADR-0049 §7.0/8e-6c add-target_date alembic round-trip via engine.begin DDL
    "tests/test_alembic_repayment_drafts_migration.py::",  # ADR-0049 §杠杆③ slice 3a add-repayment_drafts alembic round-trip via engine.begin DDL
    "tests/test_alembic_debt_constraint_hardening_migration.py::",  # ADR-0049 #4 add FK + status<->committed CHECK alembic round-trip via engine.begin DDL
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_accepts_valid_secret",
    "tests/test_auth_bootstrap.py::test_bootstrap_owner_rolls_back_if_pairing_creation_fails",
    "tests/test_uploads_no_auto_move.py::test_init_db_does_not_move_legacy_uploads",
    # True concurrency: need real independent connections (2-session races, FOR
    # UPDATE lock contention) that one shared savepoint connection cannot model.
    # Every race test follows the ``test_two_sessions_*`` naming convention, so a
    # single nodeid pattern catches them across all *_optimistic_concurrency.py.
    "::test_two_sessions",
    "tests/test_bill_split_hardening.py::test_create_invitation_row_locks_parent_expense",
    "tests/test_bill_split_debt_linkage.py::test_debt_failure_rolls_back_whole_accept",  # real rollback across the accept transaction
    "tests/test_background_task_claim.py::",  # claim atomicity across sessions
    "tests/test_background_tasks.py::",  # real background-task handler execution
    # Stale-OCC-token tests stage the conflict with a second concurrent session
    # (bumping row_version), which the shared savepoint connection can't model
    # (psycopg "savepoint does not exist").
    "tests/test_expenses_reject.py::test_stale_reject_cannot_overwrite_confirmed_expense",
    "tests/test_expenses_ocr_routes.py::test_retry_ocr_rejects_stale_pending_snapshot",
    "tests/test_merchant_alias_optimistic_concurrency.py::test_delete_alias_with_stale_token_after_concurrent_patch",
    "tests/test_merchant_alias_optimistic_concurrency.py::test_delete_then_patch_race_resolves_to_404",
    # Background enrichment (thumbnail / auto-OCR fact) is a FastAPI BackgroundTask
    # run in a threadpool thread; its writes on the shared connection don't land
    # back in the test's savepoint. These assert on that enriched output.
    "tests/test_ocr_facts.py::test_upload_link_auto_ocr_writes_fact",
    "tests/test_ocr_facts.py::test_android_upload_auto_ocr_writes_fact",
    "tests/test_uploads.py::test_upload_accepts_decodable_heic_and_generates_jpeg_thumbnail",
    "tests/test_expenses_upload_confirm.py::test_confirm_delete_after_confirm_hides_image_and_thumbnail",
    # Legacy upload-path migration runs DDL/UPDATE via engine.begin (its own
    # connection), outside the test transaction.
    "tests/test_tenant_isolation.py::test_legacy_upload_paths_migrate_into_current_tenant_dir",
    "tests/test_tenant_isolation.py::test_legacy_upload_migration_leaves_database_only_reference_untouched",
    "tests/test_tenant_isolation.py::test_legacy_upload_migration_rename_failure_keeps_original_file_and_path",
    # A read-only outer ``with SessionLocal()`` wraps a helper that commits a
    # role change; on the shared connection the outer session's close-rollback
    # discards the nested commit, so the demotion is lost (got 201, want 403).
    "tests/test_family_ledger_permissions.py::test_member_cannot_create_invitation",
    "tests/test_family_ledger_permissions.py::test_viewer_cannot_create_invitation",
    # signal-hash suppression: seeds expenses + rejects (subject_id=1) and asserts
    # the suggestion is suppressed. Passes alone and under real_db, but fails after
    # earlier learning tests in the full run — it depends on a clean per-test DB
    # (deterministic sequences / no residual state) that the rollback model, which
    # leaves PG sequences advanced across tests, doesn't provide.
    "tests/test_learning_signal_hash.py::test_backfilled_row_via_signal_hash_suppresses_suggestion",
    "tests/test_learning_signal_hash.py::test_category_reject_via_signal_hash_suppresses_suggestion",
)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    real_db = pytest.mark.real_db
    for item in items:
        # PostgreSQL isolation opt-outs (see _PG_REAL_DB_NODES). The nodeid uses
        # forward slashes on every OS.
        nodeid = item.nodeid.replace("\\", "/")
        if any(pattern in nodeid for pattern in _PG_REAL_DB_NODES):
            item.add_marker(real_db)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cleanup_runtime()
