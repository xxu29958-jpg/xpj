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

import contextlib
import os

import pytest

# Importing tests._infra.env sets os.environ before any app.* import.
from fastapi.testclient import TestClient

from scripts.run_test_lanes import RUNNER_LANE_ENV
from scripts.test_pg_contract import test_cluster_lock
from tests._infra import env
from tests._infra.client import make_test_client
from tests._infra.db import (
    cleanup_runtime,
    reset_db_state,
    transactional_isolation,
)
from tests._infra.identity import TestIdentity, seed_identity
from tests._infra.lane_policy import (
    managed_runner_configuration_violation,
    parallel_lane_configuration_violation,
    postgres_test_markers,
    stateful_selection_violation,
)
from tests._infra.worker_db import worker_database_lifecycle


@pytest.fixture(scope="session", autouse=True)
def _isolation_schema():
    """Build schema + base seed ONCE for the session (PostgreSQL isolation lane).

    Per-test ``_db_isolation`` then wraps each test in a rolled-back transaction
    (or a full reset for ``@pytest.mark.real_db`` tests).
    """
    worker_lifecycle = (
        worker_database_lifecycle(
            env.TEST_DATABASE_URL,
            worker_id=env.TEST_WORKER_ID,
            run_uid=env.TEST_RUN_UID or "",
        )
        if env.TEST_WORKER_ID is not None
        else contextlib.nullcontext()
    )
    with (
        test_cluster_lock(
            os.environ,
            exclusive=env.TEST_WORKER_ID is None,
        ),
        worker_lifecycle,
    ):
        reset_db_state()
        try:
            yield
        finally:
            cleanup_runtime()


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
    violation = managed_runner_configuration_violation(
        active_lane=os.environ.get(RUNNER_LANE_ENV),
        collection_roots=config.args,
        collect_only=bool(config.getoption("collectonly", default=False)),
        keyword=config.getoption("keyword", default="") or "",
        mark_expression=config.getoption("markexpr", default="") or "",
        deselected=config.getoption("deselect", default=()) or (),
        ignored=config.getoption("ignore", default=()) or (),
        ignore_globs=config.getoption("ignore_glob", default=()) or (),
        last_failed=bool(config.getoption("lf", default=False)),
    )
    if violation:
        raise pytest.UsageError(violation)
    violation = parallel_lane_configuration_violation(
        configured_workers=config.getoption("numprocesses", default=0),
        mark_expression=config.getoption("markexpr", default=""),
    )
    if violation:
        raise pytest.UsageError(violation)


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


def pytest_collection_finish(session: pytest.Session) -> None:
    if session.config.option.collectonly:
        return
    selected_stateful = [
        item.nodeid
        for item in session.items
        if item.get_closest_marker("stateful_serial") is not None
    ]
    violation = stateful_selection_violation(
        selected_stateful,
        xdist_worker=os.environ.get("PYTEST_XDIST_WORKER"),
        configured_workers=session.config.getoption("numprocesses", default=0),
    )
    if violation:
        raise pytest.UsageError(violation)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cleanup_runtime()
