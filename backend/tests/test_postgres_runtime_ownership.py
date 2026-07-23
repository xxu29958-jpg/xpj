from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

import conftest as suite_conftest
import pytest

from tests._infra import db as test_db
from tests._infra import worker_db


@dataclass
class _ControllerNode:
    worker_id: str
    run_uid: str = "controller-fault-injection"
    teardown_calls: int = 0

    @property
    def workerinput(self) -> dict[str, str]:
        return {"workerid": self.worker_id, "testrunuid": self.run_uid}

    def ensure_teardown(self) -> None:
        self.teardown_calls += 1


@dataclass
class _ControllerStack:
    close_calls: int = 0

    def close(self) -> None:
        self.close_calls += 1


def _lane_session(lane: str | None, *items: object) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(getoption=lambda _name: lane),
        items=list(items),
    )


def test_declared_lane_must_match_selected_marker_ownership() -> None:
    ordinary = SimpleNamespace(keywords={})
    real_db = SimpleNamespace(keywords={"real_db": True})

    suite_conftest.pytest_collection_finish(_lane_session(None, ordinary, real_db))
    suite_conftest.pytest_collection_finish(_lane_session("ordinary", ordinary))
    suite_conftest.pytest_collection_finish(_lane_session("real-db", real_db))
    with pytest.raises(pytest.UsageError, match="ordinary PostgreSQL lane"):
        suite_conftest.pytest_collection_finish(_lane_session("ordinary", ordinary, real_db))
    with pytest.raises(pytest.UsageError, match="real-db PostgreSQL lane"):
        suite_conftest.pytest_collection_finish(_lane_session("real-db", real_db, ordinary))


def test_xdist_controller_requires_explicit_parallel_lane() -> None:
    suite_conftest._assert_xdist_lane_contract(_lane_session("ordinary"))
    for lane in (None, "real-db"):
        with pytest.raises(pytest.UsageError, match="xdist is allowed only"):
            suite_conftest._assert_xdist_lane_contract(_lane_session(lane))


def test_serial_runtime_cleans_before_releasing_its_leases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    @contextmanager
    def lease(name: str):
        events.append(f"{name}:enter")
        try:
            yield ()
        finally:
            events.append(f"{name}:exit")

    monkeypatch.setattr(suite_conftest.env, "WORKER_DATABASE", None)
    monkeypatch.setattr(suite_conftest, "host_runtime_lease", lambda: lease("host"))
    monkeypatch.setattr(
        suite_conftest,
        "serial_database_lease",
        lambda *_args, **_kwargs: lease("database"),
    )
    monkeypatch.setattr(
        suite_conftest,
        "cleanup_orphan_test_runtimes",
        lambda: events.append("orphans:cleaned"),
    )
    monkeypatch.setattr(
        suite_conftest,
        "cleanup_runtime",
        lambda: events.append("runtime:cleaned"),
    )

    runtime = suite_conftest._database_runtime.__wrapped__()  # noqa: SLF001
    next(runtime)
    assert events == ["host:enter", "database:enter", "orphans:cleaned"]
    with pytest.raises(StopIteration):
        next(runtime)
    assert events == [
        "host:enter",
        "database:enter",
        "orphans:cleaned",
        "runtime:cleaned",
        "database:exit",
        "host:exit",
    ]


def test_xdist_partial_start_finalizer_is_idempotent_and_immediately_reusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_stack = _ControllerStack()
    monkeypatch.setattr(suite_conftest, "_CONTROLLER_STACK", first_stack)
    monkeypatch.setattr(suite_conftest, "_CONTROLLER_DATABASES", {})
    monkeypatch.setattr(suite_conftest, "_CONTROLLER_NODES", {})
    provision_calls: list[str] = []
    cleaned: list[str] = []

    def provision(database: worker_db.WorkerDatabase) -> None:
        provision_calls.append(database.worker_id)
        if database.worker_id == "gw1":
            raise RuntimeError("simulated second-node startup failure")

    monkeypatch.setattr(suite_conftest, "provision_worker_database", provision)
    monkeypatch.setattr(
        suite_conftest,
        "_cleanup_worker_resources",
        lambda database: cleaned.append(database.worker_id),
    )
    monkeypatch.setattr(suite_conftest, "cleanup_runtime", lambda: None)

    first = _ControllerNode("gw0")
    failed = _ControllerNode("gw1")
    suite_conftest.pytest_configure_node(first)
    with pytest.raises(RuntimeError, match="second-node"):
        suite_conftest.pytest_configure_node(failed)
    assert failed.teardown_calls == 1

    suite_conftest.pytest_unconfigure(None)
    suite_conftest.pytest_unconfigure(None)
    assert first.teardown_calls == 1
    assert cleaned == ["gw0"]
    assert provision_calls == ["gw0", "gw1"]
    assert first_stack.close_calls == 1

    second_stack = _ControllerStack()
    suite_conftest._CONTROLLER_STACK = second_stack  # noqa: SLF001
    suite_conftest.pytest_configure_node(_ControllerNode("gw2"))
    suite_conftest.pytest_unconfigure(None)
    assert second_stack.close_calls == 1


def test_xdist_worker_death_reclaims_its_database_and_runtime_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = worker_db.worker_database(
        suite_conftest.env.BASE_TEST_DATABASE_URL,
        suite_conftest.env.ADMIN_TEST_DATABASE_URL,
        "gw0",
        "worker-death-fault-injection",
    )
    node = SimpleNamespace(
        workerinput={
            "workerid": "gw0",
            "xpj_worker_database_name": database.name,
        }
    )
    cleaned: list[str] = []
    monkeypatch.setattr(suite_conftest, "_CONTROLLER_NODES", {"gw0": node})
    monkeypatch.setattr(
        suite_conftest,
        "_CONTROLLER_DATABASES",
        {database.name: database},
    )
    monkeypatch.setattr(
        suite_conftest,
        "_cleanup_worker_resources",
        lambda owned: cleaned.append(owned.name),
    )

    suite_conftest.pytest_testnodedown(node, RuntimeError("worker exited"))
    suite_conftest.pytest_testnodedown(node, None)

    assert cleaned == [database.name]
    assert suite_conftest._CONTROLLER_NODES == {}  # noqa: SLF001
    assert suite_conftest._CONTROLLER_DATABASES == {}  # noqa: SLF001


def test_runtime_cleanup_removes_worker_upload_and_data_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    upload_root = tmp_path / "uploads"
    data_root = tmp_path / "data"
    runtime_id = "xdist_0123456789_gw0"
    upload = upload_root / f"pytest_test_{runtime_id}"
    data = data_root / runtime_id
    upload.mkdir(parents=True)
    data.mkdir(parents=True)
    (upload / "artifact").write_text("test", encoding="utf-8")
    (data / "artifact").write_text("test", encoding="utf-8")
    monkeypatch.setattr(test_db, "_UPLOAD_RUNTIME_ROOT", upload_root)
    monkeypatch.setattr(test_db, "_DATA_RUNTIME_ROOT", data_root)

    test_db.cleanup_test_runtime(runtime_id)

    assert not upload.exists()
    assert not data.exists()


def test_runtime_cleanup_refuses_root_or_outside_path(tmp_path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    outside = tmp_path / "outside"

    with pytest.raises(RuntimeError, match="outside"):
        test_db._remove_owned_runtime(root, root=root)  # noqa: SLF001
    with pytest.raises(RuntimeError, match="outside"):
        test_db._remove_owned_runtime(outside, root=root)  # noqa: SLF001
    with pytest.raises(ValueError, match="invalid test runtime id"):
        test_db.cleanup_test_runtime("../outside")


def test_runtime_cleanup_refuses_top_level_and_nested_links(tmp_path) -> None:
    root = tmp_path / "runtime"
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "must-survive"
    sentinel.write_text("foreign", encoding="utf-8")
    top_level_link = root / "top-level-link"
    root_link = tmp_path / "runtime-root-link"
    root.mkdir()
    try:
        top_level_link.symlink_to(outside, target_is_directory=True)
        root_link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory links are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="reparse point"):
        test_db._remove_owned_runtime(top_level_link, root=root)  # noqa: SLF001
    (outside / "owned").mkdir()
    with pytest.raises(RuntimeError, match="reparse point"):
        test_db._remove_owned_runtime(root_link / "owned", root=root_link)  # noqa: SLF001

    owned = root / "owned"
    owned.mkdir()
    (owned / "nested-link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="reparse point"):
        test_db._remove_owned_runtime(owned, root=root)  # noqa: SLF001
    assert sentinel.read_text(encoding="utf-8") == "foreign"


def test_host_runtime_lease_rejects_a_competing_suite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(test_db, "_RUNTIME_LOCK_PATH", tmp_path / "runtime.lock")
    monkeypatch.setattr(test_db, "_RUNTIME_LOCK_TIMEOUT_SECONDS", 0.01)

    with (
        test_db.host_runtime_lease(),
        pytest.raises(RuntimeError, match="another pytest session"),
        test_db.host_runtime_lease(),
    ):
        raise AssertionError("competing suite must not enter the runtime lease")

    with test_db.host_runtime_lease():
        pass


def test_runtime_lock_propagates_non_contention_os_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    if test_db.os.name == "nt":
        import msvcrt as lock_module

        operation = "locking"
    else:
        import fcntl as lock_module

        operation = "flock"

    def fail_lock(*_args) -> None:
        raise OSError(errno.EIO, "simulated lock I/O failure")

    monkeypatch.setattr(lock_module, operation, fail_lock)
    lock_path = tmp_path / "runtime.lock"
    with lock_path.open("w+b", buffering=0) as handle:
        handle.write(b"\0")
        with pytest.raises(OSError, match="simulated lock I/O failure"):
            test_db._try_lock_runtime_file(handle)  # noqa: SLF001


def test_runtime_cleanup_propagates_filesystem_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    root = tmp_path / "runtime"
    target = root / "run"
    target.mkdir(parents=True)

    def deny_cleanup(_path) -> None:
        raise PermissionError("denied")

    if os.name == "nt":
        from tests._infra import windows_tree

        monkeypatch.setattr(windows_tree, "remove_tree_exact", deny_cleanup)
    else:
        deny_cleanup.avoids_symlink_attacks = True
        monkeypatch.setattr(test_db.shutil, "rmtree", deny_cleanup)

    with pytest.raises(PermissionError, match="denied"):
        test_db._remove_owned_runtime(target, root=root)  # noqa: SLF001
