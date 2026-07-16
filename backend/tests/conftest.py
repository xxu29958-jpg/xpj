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
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

# Importing tests._infra.env sets os.environ before any app.* import.
from fastapi.testclient import TestClient

from scripts.pytest_execution_contract import (
    pytest_execution_membership_violation as execution_membership_violation,
)
from scripts.run_test_lanes import (
    RUNNER_EXPECTED_COUNT_ENV,
    RUNNER_EXPECTED_DIGEST_ENV,
    RUNNER_HANDSHAKE_PATH_ENV,
    RUNNER_HANDSHAKE_TOKEN_ENV,
    RUNNER_LANE_ENV,
    runner_handshake_payload,
)
from scripts.test_pg_contract import (
    start_windows_parent_watchdog,
    test_cluster_lock,
    test_postgres_consumer_lease,
    test_postgres_credential_environment,
)
from tests._infra import env
from tests._infra.client import make_test_client
from tests._infra.db import (
    cleanup_runtime,
    reset_db_state,
    transactional_isolation,
)
from tests._infra.identity import TestIdentity, seed_identity
from tests._infra.lane_policy import (
    managed_runner_completion_violation,
    managed_runner_configuration_violation,
    managed_runner_outcome_violation,
    managed_runner_selection_violation,
    managed_runner_worker_violation,
    parallel_lane_configuration_violation,
    postgres_marker_contract_violation,
    stateful_selection_violation,
    xdist_worker_identity_violation,
)
from tests._infra.postgres_resource_contract import (
    postgres_source_marker_contract_violation,
    postgres_worker_isolation_boundary,
)
from tests._infra.worker_db import worker_database_lifecycle


def _is_xdist_worker(config: pytest.Config) -> bool:
    """Use xdist's runtime-owned config marker, never ambient environment."""

    return hasattr(config, "workerinput")


def _xdist_worker_id(node: object) -> str:
    return str(node.gateway.id)  # type: ignore[attr-defined]


@pytest.fixture(scope="session", autouse=True)
@postgres_worker_isolation_boundary
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
@postgres_worker_isolation_boundary
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


def _initialize_runner_state(config: pytest.Config) -> None:
    config._xpj_xdist_ready_workers = set()  # type: ignore[attr-defined]
    config._xpj_xdist_down_workers = set()  # type: ignore[attr-defined]
    config._xpj_xdist_worker_errors = {}  # type: ignore[attr-defined]
    config._xpj_consumer_lease = None  # type: ignore[attr-defined]
    config._xpj_postgres_credential_environment = None  # type: ignore[attr-defined]


def _register_postgres_markers(config: pytest.Config) -> None:
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
        "cluster_serial: PostgreSQL cluster-level test that must run in the exclusive stateful lane.",
    )
    config.addinivalue_line(
        "markers",
        "parallel_safe: explicit resource class for a new test that stays inside "
        "the per-worker transaction/database boundary.",
    )


def _validate_managed_runner_configuration(config: pytest.Config) -> None:
    worker_input = getattr(config, "workerinput", None)
    runtime_worker = (
        str(worker_input.get("workerid"))
        if isinstance(worker_input, dict) and worker_input.get("workerid") is not None
        else None
    )
    violation = xdist_worker_identity_violation(
        ambient_worker=env.TEST_WORKER_ID,
        runtime_worker=runtime_worker,
    )
    if violation:
        raise pytest.UsageError(violation)
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
        optimized=bool(sys.flags.optimize),
    )
    if violation:
        raise pytest.UsageError(violation)
    violation = parallel_lane_configuration_violation(
        configured_workers=config.getoption("numprocesses", default=0),
        mark_expression=config.getoption("markexpr", default=""),
    )
    if violation:
        raise pytest.UsageError(violation)


def _enter_postgres_runtime_contract(config: pytest.Config) -> None:
    if not config.getoption("collectonly", default=False):
        lease = test_postgres_consumer_lease(env.TEST_DATABASE_URL)
        try:
            lease.__enter__()
        except RuntimeError as exc:
            raise pytest.UsageError(str(exc)) from exc
        config._xpj_consumer_lease = lease  # type: ignore[attr-defined]
        credential_environment = test_postgres_credential_environment(
            env.TEST_DATABASE_URL,
            os.environ,
        )
        try:
            credential_environment.__enter__()
        except RuntimeError as exc:
            lease.__exit__(None, None, None)
            config._xpj_consumer_lease = None  # type: ignore[attr-defined]
            raise pytest.UsageError(str(exc)) from exc
        config._xpj_postgres_credential_environment = credential_environment  # type: ignore[attr-defined]
    active_lane = os.environ.get(RUNNER_LANE_ENV)
    if active_lane:
        start_windows_parent_watchdog(label=f"PostgreSQL {active_lane} pytest")
        if not _is_xdist_worker(config):
            handshake_path = os.environ.get(RUNNER_HANDSHAKE_PATH_ENV)
            handshake_token = os.environ.get(RUNNER_HANDSHAKE_TOKEN_ENV)
            if not handshake_path or not handshake_token:
                raise pytest.UsageError("Managed PostgreSQL test lane is missing its runner handshake contract.")
            if Path(handshake_path).exists():
                raise pytest.UsageError("Managed PostgreSQL test lane handshake path already exists.")


def pytest_configure(config: pytest.Config) -> None:
    _initialize_runner_state(config)
    _register_postgres_markers(config)
    _validate_managed_runner_configuration(config)
    _enter_postgres_runtime_contract(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    credential_environment = getattr(
        config,
        "_xpj_postgres_credential_environment",
        None,
    )
    if credential_environment is not None:
        credential_environment.__exit__(None, None, None)
    lease = getattr(config, "_xpj_consumer_lease", None)
    if lease is not None:
        lease.__exit__(None, None, None)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodeready(node: object) -> None:
    node.config._xpj_xdist_ready_workers.add(_xdist_worker_id(node))  # type: ignore[attr-defined]


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object, error: object | None) -> None:
    worker_id = _xdist_worker_id(node)
    node.config._xpj_xdist_down_workers.add(worker_id)  # type: ignore[attr-defined]
    if error is not None:
        node.config._xpj_xdist_worker_errors[worker_id] = str(error)  # type: ignore[attr-defined]


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> Generator[None, None, None]:
    """Verify explicit resource metadata and the final managed partition."""

    for item in items:
        marker_names = {marker.name for marker in item.iter_markers()}
        violation = postgres_marker_contract_violation(item.nodeid, marker_names)
        if violation is None:
            violation = postgres_source_marker_contract_violation(item, marker_names)
        if violation:
            raise pytest.UsageError(violation)

    collected_nodeids = tuple(item.nodeid for item in items)
    stateful_nodeids = tuple(item.nodeid for item in items if item.get_closest_marker("stateful_serial") is not None)
    yield

    violation = managed_runner_selection_violation(
        active_lane=os.environ.get(RUNNER_LANE_ENV),
        collected_nodeids=collected_nodeids,
        stateful_nodeids=stateful_nodeids,
        selected_nodeids=tuple(item.nodeid for item in items),
    )
    if violation is None and os.environ.get(RUNNER_LANE_ENV):
        violation = execution_membership_violation(
            label=f"PostgreSQL {os.environ[RUNNER_LANE_ENV]} lane",
            selected_nodeids=tuple(item.nodeid for item in items),
            expected_count=os.environ.get(RUNNER_EXPECTED_COUNT_ENV),
            expected_digest=os.environ.get(RUNNER_EXPECTED_DIGEST_ENV),
        )
    if violation:
        raise pytest.UsageError(violation)


def pytest_collection_finish(session: pytest.Session) -> None:
    if session.config.option.collectonly:
        return
    selected_stateful = [
        item.nodeid for item in session.items if item.get_closest_marker("stateful_serial") is not None
    ]
    violation = stateful_selection_violation(
        selected_stateful,
        xdist_worker="xdist-worker" if _is_xdist_worker(session.config) else None,
        configured_workers=session.config.getoption("numprocesses", default=0),
    )
    if violation:
        raise pytest.UsageError(violation)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    cleanup_runtime()
    if _is_xdist_worker(session.config):
        return
    active_lane = os.environ.get(RUNNER_LANE_ENV)
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    outcome_counts = (
        {name: len(terminal.stats.get(name, ())) for name in ("skipped", "xfailed", "xpassed")}
        if terminal is not None
        else None
    )
    violation = managed_runner_outcome_violation(
        active_lane=active_lane,
        outcome_counts=outcome_counts,
    )
    if violation is None:
        violation = managed_runner_worker_violation(
            active_lane=active_lane,
            configured_workers=session.config.getoption("numprocesses", default=0),
            ready_workers=session.config._xpj_xdist_ready_workers,  # type: ignore[attr-defined]
            down_workers=session.config._xpj_xdist_down_workers,  # type: ignore[attr-defined]
            worker_errors=session.config._xpj_xdist_worker_errors,  # type: ignore[attr-defined]
        )
    if violation is None:
        violation = managed_runner_completion_violation(
            active_lane=active_lane,
            exit_status=exitstatus,
            tests_collected=session.testscollected,
            passed_count=(len(terminal.stats.get("passed", ())) if terminal is not None else None),
        )
    if violation:
        if terminal is not None:
            terminal.write_sep("!", violation, red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return
    if active_lane:
        handshake_path = os.environ.get(RUNNER_HANDSHAKE_PATH_ENV)
        handshake_token = os.environ.get(RUNNER_HANDSHAKE_TOKEN_ENV)
        expected_count = os.environ.get(RUNNER_EXPECTED_COUNT_ENV)
        expected_digest = os.environ.get(RUNNER_EXPECTED_DIGEST_ENV)
        try:
            path = Path(handshake_path or "")
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    runner_handshake_payload(
                        active_lane,
                        handshake_token or "",
                        int(expected_count or "0"),
                        expected_digest or "",
                    )
                )
        except OSError:
            if terminal is not None:
                terminal.write_sep(
                    "!",
                    "Managed PostgreSQL test lane could not create its completion handshake.",
                    red=True,
                )
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
