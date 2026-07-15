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

from tests._infra import env
from tests._infra.client import make_test_client
from tests._infra.db import (
    cleanup_runtime,
    reset_db_state,
    transactional_isolation,
)
from tests._infra.identity import TestIdentity, seed_identity
from tests._infra.lane_policy import postgres_test_markers
from tests._infra.worker_db import drop_worker_database, recreate_worker_database


@pytest.fixture(scope="session", autouse=True)
def _isolation_schema():
    """Build schema + base seed ONCE for the session (PostgreSQL isolation lane).

    Per-test ``_db_isolation`` then wraps each test in a rolled-back transaction
    (or a full reset for ``@pytest.mark.real_db`` tests).
    """
    if env.TEST_WORKER_ID is not None:
        recreate_worker_database(env.TEST_DATABASE_URL)
    try:
        reset_db_state()
        yield
    finally:
        cleanup_runtime()
        if env.TEST_WORKER_ID is not None:
            drop_worker_database(env.TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def _settings_cache_isolation():
    """Keep process-wide settings snapshots from crossing test boundaries."""
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _db_isolation(
    request: pytest.FixtureRequest,
    _settings_cache_isolation,
):
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
    config.addinivalue_line(
        "markers",
        "stateful_serial: committed-state, schema, migration, recovery, or "
        "cross-process test that must run outside the xdist parallel lane.",
    )
    config.addinivalue_line(
        "markers",
        "cluster_serial: PostgreSQL cluster-level test that must run in the "
        "exclusive stateful lane.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    markers = {
        "real_db": pytest.mark.real_db,
        "stateful_serial": pytest.mark.stateful_serial,
        "cluster_serial": pytest.mark.cluster_serial,
    }
    for item in items:
        for marker_name in postgres_test_markers(item.nodeid):
            item.add_marker(markers[marker_name])
