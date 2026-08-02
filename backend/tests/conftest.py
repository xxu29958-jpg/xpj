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

import os
from contextlib import ExitStack

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from xdist import is_xdist_controller

from scripts.run_postgres_pytest_lane import (
    PARALLEL_POSTGRES_PYTEST_LANE,
    POSTGRES_PYTEST_LANE_DEST,
    POSTGRES_PYTEST_LANE_MARKERS,
    POSTGRES_PYTEST_LANE_OPTION,
    POSTGRES_PYTEST_SHARD_COUNT_DEST,
    POSTGRES_PYTEST_SHARD_COUNT_OPTION,
    POSTGRES_PYTEST_SHARD_INDEX_DEST,
    POSTGRES_PYTEST_SHARD_INDEX_OPTION,
    validate_lane_collection,
    validate_shard_coordinates,
)

# Importing tests._infra.env sets os.environ before any app.* import.
from tests._infra import env  # noqa: F401
from tests._infra.client import make_test_client
from tests._infra.db import (
    cleanup_orphan_test_runtimes,
    cleanup_runtime,
    cleanup_test_runtime,
    host_runtime_lease,
    reset_db_state,
    transactional_isolation,
)
from tests._infra.identity import TestIdentity, seed_identity
from tests._infra.worker_db import (
    WorkerDatabase,
    drop_worker_database,
    provision_worker_database,
    serial_database_lease,
    verify_worker_database,
    worker_database,
)

pytest_plugins = ("tests._infra.postgres_sharding_plugin",)

_CONTROLLER_STACK: ExitStack | None = None
_CONTROLLER_DATABASES: dict[str, WorkerDatabase] = {}
_CONTROLLER_NODES: dict[str, object] = {}
_CLEANUP_ERRORS = (OSError, RuntimeError, ValueError, psycopg.Error, SQLAlchemyError)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("xpj-postgres")
    group.addoption(
        POSTGRES_PYTEST_LANE_OPTION,
        action="store",
        choices=tuple(POSTGRES_PYTEST_LANE_MARKERS),
        default=None,
        dest=POSTGRES_PYTEST_LANE_DEST,
        help="declare the PostgreSQL responsibility lane selected by the runner",
    )
    group.addoption(
        POSTGRES_PYTEST_SHARD_INDEX_OPTION,
        action="store",
        type=int,
        default=0,
        dest=POSTGRES_PYTEST_SHARD_INDEX_DEST,
        help="zero-based PostgreSQL lane shard index",
    )
    group.addoption(
        POSTGRES_PYTEST_SHARD_COUNT_OPTION,
        action="store",
        type=int,
        default=1,
        dest=POSTGRES_PYTEST_SHARD_COUNT_DEST,
        help="PostgreSQL lane shard count",
    )


@pytest.fixture(scope="session", autouse=True)
def _database_runtime():
    """Own the generated worker DB, or serialize access to the base DB."""
    database = env.WORKER_DATABASE
    if database is None:
        with ExitStack() as stack:
            stack.enter_context(host_runtime_lease())
            stack.enter_context(
                serial_database_lease(
                    env.ADMIN_TEST_DATABASE_URL,
                    cleanup_runtime=cleanup_test_runtime,
                )
            )
            cleanup_orphan_test_runtimes()
            try:
                yield
            finally:
                cleanup_runtime()
        return

    verify_worker_database(database)
    try:
        yield
    finally:
        cleanup_runtime()


@pytest.fixture(scope="session", autouse=True)
def _isolation_schema(_database_runtime):
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
    try:
        validate_shard_coordinates(
            lane=config.getoption(POSTGRES_PYTEST_LANE_DEST),
            shard_index=config.getoption(POSTGRES_PYTEST_SHARD_INDEX_DEST),
            shard_count=config.getoption(POSTGRES_PYTEST_SHARD_COUNT_DEST),
        )
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    worker_input = getattr(config, "workerinput", None)
    worker_id = os.environ.get("PYTEST_XDIST_WORKER")
    run_uid = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if worker_input is None:
        if worker_id is not None or run_uid is not None:
            raise pytest.UsageError("xdist environment present outside an xdist worker")
        return
    if worker_id != worker_input.get("workerid") or run_uid != worker_input.get("testrunuid"):
        raise pytest.UsageError("xdist environment does not match worker runtime identity")
    if env.WORKER_DATABASE is None:
        raise pytest.UsageError("xdist worker database was not derived before app import")
    if worker_input.get("xpj_worker_database_name") != env.WORKER_DATABASE.name:
        raise pytest.UsageError("xdist worker database does not match controller ownership")


def pytest_collection_finish(session: pytest.Session) -> None:
    """Prove that the runner's declared lane matches the selected markers."""
    lane = session.config.getoption(POSTGRES_PYTEST_LANE_DEST)
    selected_real_db = ["real_db" in item.keywords for item in session.items]
    try:
        validate_lane_collection(lane=lane, selected_real_db=selected_real_db)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc


def _assert_xdist_lane_contract(session: pytest.Session) -> None:
    lane = session.config.getoption(POSTGRES_PYTEST_LANE_DEST)
    if lane != PARALLEL_POSTGRES_PYTEST_LANE:
        raise pytest.UsageError(
            "xdist is allowed only through the declared ordinary PostgreSQL lane; "
            "use python -m scripts.run_postgres_pytest_lane --lane ordinary --workers 2"
        )


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session: pytest.Session) -> None:
    """Acquire one cluster lease before xdist starts any worker."""
    global _CONTROLLER_STACK
    if not is_xdist_controller(session):
        return
    _assert_xdist_lane_contract(session)
    if _CONTROLLER_STACK is not None:
        raise pytest.UsageError("xdist controller database runtime already exists")
    stack = ExitStack()
    try:
        stack.enter_context(host_runtime_lease())
        stack.enter_context(
            serial_database_lease(
                env.ADMIN_TEST_DATABASE_URL,
                cleanup_runtime=cleanup_test_runtime,
            )
        )
        cleanup_orphan_test_runtimes()
    except _CLEANUP_ERRORS:
        stack.close()
        raise
    _CONTROLLER_STACK = stack


def pytest_configure_node(node) -> None:
    """Controller creates each worker DB before the worker process starts."""
    if _CONTROLLER_STACK is None:
        raise pytest.UsageError("xdist controller does not own the test cluster")
    worker_id = node.workerinput["workerid"]
    if worker_id in _CONTROLLER_NODES:
        raise pytest.UsageError(f"duplicate xdist worker runtime: {worker_id}")
    _CONTROLLER_NODES[worker_id] = node
    database = worker_database(
        env.BASE_TEST_DATABASE_URL,
        env.ADMIN_TEST_DATABASE_URL,
        worker_id,
        node.workerinput["testrunuid"],
    )
    provisioned = False
    try:
        provision_worker_database(database)
        provisioned = True
    finally:
        if not provisioned:
            _CONTROLLER_NODES.pop(worker_id, None)
            node.ensure_teardown()
    _CONTROLLER_DATABASES[database.name] = database
    node.workerinput["xpj_worker_database_name"] = database.name


def pytest_testnodedown(node, error) -> None:
    """Controller-side cleanup for a worker that died before fixture teardown."""
    _CONTROLLER_NODES.pop(node.workerinput.get("workerid"), None)
    name = node.workerinput.get("xpj_worker_database_name")
    database = _CONTROLLER_DATABASES.get(name)
    if database is None:
        return
    _cleanup_worker_resources(database)
    del _CONTROLLER_DATABASES[database.name]


def _cleanup_worker_resources(database: WorkerDatabase) -> None:
    first_error: Exception | None = None
    try:
        cleanup_test_runtime(database.runtime_id)
    except _CLEANUP_ERRORS as exc:
        first_error = exc
    try:
        if first_error is None:
            drop_worker_database(database)
    except _CLEANUP_ERRORS as exc:
        first_error = first_error or exc
    if first_error is not None:
        raise first_error


def _finalize_controller_runtime() -> None:
    global _CONTROLLER_STACK
    if _CONTROLLER_STACK is None and not _CONTROLLER_DATABASES and not _CONTROLLER_NODES:
        return

    first_error: Exception | None = None
    try:
        for node in tuple(_CONTROLLER_NODES.values()):
            try:
                node.ensure_teardown()
            except _CLEANUP_ERRORS as exc:
                first_error = first_error or exc
        for database in tuple(_CONTROLLER_DATABASES.values()):
            try:
                _cleanup_worker_resources(database)
                del _CONTROLLER_DATABASES[database.name]
            except _CLEANUP_ERRORS as exc:
                first_error = first_error or exc
        try:
            cleanup_runtime()
        except _CLEANUP_ERRORS as exc:
            first_error = first_error or exc
    finally:
        stack = _CONTROLLER_STACK
        _CONTROLLER_STACK = None
        _CONTROLLER_DATABASES.clear()
        _CONTROLLER_NODES.clear()
        if stack is not None:
            try:
                stack.close()
            except _CLEANUP_ERRORS as exc:
                first_error = first_error or exc
    if first_error is not None:
        raise first_error


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if is_xdist_controller(session):
        _finalize_controller_runtime()


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """Recover controller resources when startup fails before sessionfinish."""
    _finalize_controller_runtime()
