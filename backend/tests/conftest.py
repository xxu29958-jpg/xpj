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
from tests._infra.db import cleanup_runtime, reset_db_state
from tests._infra.identity import TestIdentity, seed_identity


@pytest.fixture()
def identity() -> TestIdentity:
    reset_db_state()
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
        "file_backed_only: test only meaningful against a file-backed SQLite; "
        "skipped under the default in-memory lane. Run via XPJ_TEST_FILE_BACKED=1.",
    )
    config.addinivalue_line(
        "markers",
        "sqlite_only: test exercises SQLite-only machinery (the migrate_sqlite_schema "
        "replay, PRAGMA, file backup/validation) that no-ops on PostgreSQL; skipped on "
        "the ADR-0041 Postgres lane (XPJ_TEST_DATABASE_URL=postgresql+psycopg://…).",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    from app.database import settings as _settings

    url = _settings.database_url
    is_sqlite = url.startswith("sqlite")
    is_in_memory = ":memory:" in url or url == "sqlite://"
    # File-backed SQLite (verify_project / CI file-backed lane) runs the full
    # suite, including file_backed_only + the SQLite migrator tests.
    if is_sqlite and not is_in_memory:
        return

    on_postgres = not is_sqlite
    skip_file_backed = pytest.mark.skip(
        reason="file_backed_only: requires file-backed SQLite (set XPJ_TEST_FILE_BACKED=1)."
    )
    skip_sqlite_only = pytest.mark.skip(
        reason="sqlite_only: SQLite-only machinery, not run on the PostgreSQL lane."
    )
    for item in items:
        if "file_backed_only" in item.keywords:
            item.add_marker(skip_file_backed)
        # The Postgres lane skips SQLite-only machinery: the migrate_sqlite_schema
        # replay tests (which exercise a path that no-ops on PostgreSQL) and
        # anything explicitly marked ``sqlite_only``.
        if on_postgres and (
            "sqlite_only" in item.keywords
            or "test_database_migration" in item.module.__name__
        ):
            item.add_marker(skip_sqlite_only)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cleanup_runtime()
