from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_packaging_tests
from scripts.packaging_pytest_contract import packaging_xdist_group
from scripts.pytest_execution_contract import (
    PytestCollectionSnapshot,
    application_config_environment_keys,
    parse_pytest_collection,
    parse_pytest_targets_collection,
    pytest_execution_environment,
    pytest_execution_membership_violation,
    pytest_nodeid_digest,
    pytest_target_digest,
)

pytestmark = pytest.mark.parallel_safe


def _load_packaging_conftest() -> ModuleType:
    conftest_path = run_packaging_tests.BACKEND_ROOT / "packaging" / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location(
        "xpj_packaging_conftest_probe",
        conftest_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pytest_collection_digest_is_order_independent() -> None:
    first = ("tests/test_a.py::test_one", "tests/test_b.py::test_two")
    second = tuple(reversed(first))

    assert pytest_nodeid_digest(first) == pytest_nodeid_digest(second)


def test_pytest_execution_environment_removes_ambient_selectors() -> None:
    environment = pytest_execution_environment(
        {
            "PYTEST_ADDOPTS": "--collect-only -k owner",
            "PYTEST_PLUGINS": "ambient_plugin",
            "PYTEST_XDIST_WORKER": "gw7",
            "PYTHONOPTIMIZE": "2",
            "PYTHONPATH": "ambient-import-root",
            "PGHOSTADDR": "203.0.113.8",
            "PGSERVICE": "foreign-cluster",
            "ENABLE_HTTP_BOOTSTRAP": "true",
            "HTTP_BOOTSTRAP_SECRET": "ambient-secret",
            "TICKETBOX_DATA_DIR": "ambient-data-root",
            "XPJ_BACKGROUND_TASK_INLINE": "1",
            "XPJ_TEST_RUNNER_LANE": "parallel",
            "XPJ_PYTEST_EXECUTION_EXPECTED_COUNT": "1",
            "KEEP": "yes",
        }
    )

    assert environment == {
        "KEEP": "yes",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


def test_application_environment_contract_tracks_runtime_configuration() -> None:
    keys = application_config_environment_keys()

    assert {
        "DATABASE_URL",
        "ENABLE_HTTP_BOOTSTRAP",
        "HTTP_BOOTSTRAP_SECRET",
        "TICKETBOX_DATA_DIR",
        "XPJ_BACKGROUND_TASK_INLINE",
    } <= keys
    assert "PROGRAMFILES" not in keys


def test_collection_parser_requires_every_reported_nodeid() -> None:
    parsed = parse_pytest_collection(
        "tests",
        subprocess.CompletedProcess(
            ["pytest"],
            0,
            "tests/test_a.py::test_one\n1 test collected in 0.01s\n",
            "",
        ),
        allow_empty=False,
    )
    assert parsed == PytestCollectionSnapshot(("tests/test_a.py::test_one",))

    with pytest.raises(RuntimeError, match="emitted 1 node ids"):
        parse_pytest_collection(
            "tests",
            subprocess.CompletedProcess(
                ["pytest"],
                0,
                "tests/test_a.py::test_one\n2 tests collected in 0.01s\n",
                "",
            ),
            allow_empty=False,
        )


def test_multi_target_collection_and_target_digest_are_order_independent() -> None:
    targets = ("tests/test_a.py", "tests/test_b.py")
    parsed = parse_pytest_targets_collection(
        tuple(reversed(targets)),
        subprocess.CompletedProcess(
            ["pytest"],
            0,
            "tests/test_b.py::test_two\n"
            "tests/test_a.py::test_one\n"
            "2 tests collected in 0.01s\n",
            "",
        ),
        allow_empty=False,
    )

    assert parsed == PytestCollectionSnapshot(
        ("tests/test_b.py::test_two", "tests/test_a.py::test_one")
    )
    assert pytest_target_digest(targets) == pytest_target_digest(tuple(reversed(targets)))
    assert pytest_target_digest(("tests\\test_a.py",)) == pytest_target_digest(
        ("tests/test_a.py",)
    )


def test_execution_membership_rejects_precollection_omission() -> None:
    expected = ("tests/test_a.py::test_one", "tests/test_b.py::test_two")
    violation = pytest_execution_membership_violation(
        label="parallel",
        selected_nodeids=expected[:1],
        expected_count=str(len(expected)),
        expected_digest=pytest_nodeid_digest(expected),
    )

    assert violation is not None
    assert "independent collection" in violation
    empty_digest = pytest_nodeid_digest(())
    assert (
        pytest_execution_membership_violation(
            label="empty resource",
            selected_nodeids=(),
            expected_count="0",
            expected_digest=empty_digest,
            allow_empty=True,
        )
        is None
    )
    assert (
        pytest_execution_membership_violation(
            label="required resource",
            selected_nodeids=(),
            expected_count="0",
            expected_digest=empty_digest,
        )
        is not None
    )


def test_packaging_runner_clears_filters_and_requires_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = PytestCollectionSnapshot(
        ("packaging/tests/test_installer.py::test_upgrade",)
    )
    observed: dict[str, object] = {}
    collection_calls = 0
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only -k version")
    monkeypatch.setenv("PYTEST_PLUGINS", "ambient_plugin")
    monkeypatch.setenv("PYTHONPATH", "ambient-import-root")

    def collect(*_args, **_kwargs):
        nonlocal collection_calls
        collection_calls += 1
        return snapshot

    monkeypatch.setattr(run_packaging_tests, "collect_pytest_snapshot", collect)

    def execute(
        command: list[str],
        *,
        check: bool,
        cwd: Path,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, cwd=cwd, environment=env)
        handshake = Path(env[run_packaging_tests.PYTEST_HANDSHAKE_PATH_ENV])
        handshake.write_text(
            run_packaging_tests.pytest_execution_handshake_payload(
                "packaging",
                env[run_packaging_tests.PYTEST_HANDSHAKE_TOKEN_ENV],
                snapshot.count,
                snapshot.digest,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run_packaging_tests.subprocess, "run", execute)

    assert run_packaging_tests.run_packaging_tests() == 0
    assert collection_calls == 1
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTEST_PLUGINS" not in environment
    assert "PYTHONPATH" not in environment
    assert environment[run_packaging_tests.STRICT_WINDOWS_RUNTIME_ENV] == "1"
    assert observed["cwd"] == run_packaging_tests.BACKEND_ROOT
    assert "-o" in observed["command"]
    assert "--durations=20" in observed["command"]
    assert "--durations-min=0.5" in observed["command"]
    assert "xdist.plugin" in observed["command"]
    assert observed["command"][observed["command"].index("-n") + 1] == "3"
    assert "--dist=loadgroup" in observed["command"]
    assert "--max-worker-restart=0" in observed["command"]


def test_packaging_runner_rejects_success_without_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = PytestCollectionSnapshot(
        ("packaging/tests/test_installer.py::test_upgrade",)
    )
    monkeypatch.setattr(
        run_packaging_tests,
        "collect_pytest_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        run_packaging_tests.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    assert run_packaging_tests.run_packaging_tests() == run_packaging_tests.HANDSHAKE_FAILURE_EXIT_CODE


def test_packaging_watchdog_covers_controller_and_each_xdist_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaging_conftest()
    labels: list[str] = []
    monkeypatch.setattr(
        module,
        "start_windows_parent_watchdog",
        lambda *, label: labels.append(label),
    )

    module._start_strict_runtime_watchdog(SimpleNamespace())  # noqa: SLF001
    module._start_strict_runtime_watchdog(  # noqa: SLF001
        SimpleNamespace(workerinput={"workerid": "gw0"})
    )

    assert labels == [
        "strict packaging pytest controller",
        "strict packaging pytest xdist worker",
    ]


def test_packaging_strict_runtime_rejects_module_level_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaging_conftest()
    monkeypatch.setenv(module._STRICT_RUNTIME_ENV, "1")  # noqa: SLF001

    class Terminal:
        stats = {
            "passed": (SimpleNamespace(nodeid="packaging/tests/test_ok.py::test_ok"),),
            "skipped": (SimpleNamespace(nodeid="packaging/tests/test_optional.py"),),
        }

        def write_sep(self, *_args, **_kwargs) -> None:
            return None

    terminal = Terminal()
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(get_plugin=lambda _name: terminal),
        _xpj_xdist_ready_workers={"gw0", "gw1", "gw2"},
        _xpj_xdist_down_workers={"gw0", "gw1", "gw2"},
        _xpj_xdist_worker_errors={},
    )
    session = SimpleNamespace(
        config=config,
        testscollected=1,
        exitstatus=pytest.ExitCode.OK,
    )

    module.pytest_sessionfinish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_packaging_sessionfinish_rejects_late_worker_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_packaging_conftest()
    monkeypatch.setenv(module._STRICT_RUNTIME_ENV, "1")  # noqa: SLF001
    monkeypatch.setattr(module.sys, "platform", "win32")
    handshake = tmp_path / "late-worker.handshake"
    nodeid = "packaging/tests/test_ok.py::test_ok"
    monkeypatch.setenv(module.PYTEST_HANDSHAKE_PATH_ENV, str(handshake))
    monkeypatch.setenv(module.PYTEST_HANDSHAKE_TOKEN_ENV, "late-worker-token")
    monkeypatch.setenv(module.PYTEST_EXPECTED_COUNT_ENV, "1")
    monkeypatch.setenv(module.PYTEST_EXPECTED_DIGEST_ENV, pytest_nodeid_digest((nodeid,)))

    class Terminal:
        stats = {"passed": (SimpleNamespace(nodeid=nodeid),)}

        def write_sep(self, *_args, **_kwargs) -> None:
            return None

    terminal = Terminal()
    config = SimpleNamespace(
        pluginmanager=SimpleNamespace(get_plugin=lambda _name: terminal),
    )
    module._initialize_runner_state(config)  # noqa: SLF001
    for worker_id in ("gw0", "gw1", "gw2"):
        node = SimpleNamespace(
            config=config,
            gateway=SimpleNamespace(id=worker_id),
        )
        module.pytest_testnodeready(node)
        error = RuntimeError("late worker crash") if worker_id == "gw2" else None
        module.pytest_testnodedown(node, error)
    session = SimpleNamespace(
        config=config,
        testscollected=1,
        exitstatus=pytest.ExitCode.OK,
    )

    module.pytest_sessionfinish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert not handshake.exists()


def test_packaging_collection_rejects_authored_scheduler_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_packaging_conftest()
    monkeypatch.delenv(module._STRICT_RUNTIME_ENV, raising=False)  # noqa: SLF001

    class AuthoredItem:
        def __init__(self, marker: SimpleNamespace) -> None:
            self.nodeid = f"packaging/tests/test_bad.py::test_{marker.name}"
            self.marker = marker

        def get_closest_marker(self, name: str) -> SimpleNamespace | None:
            return self.marker if name == self.marker.name else None

    marker = SimpleNamespace(name="xdist_group")
    hook = module.pytest_collection_modifyitems([AuthoredItem(marker)])
    with pytest.raises(pytest.UsageError, match=marker.name):
        next(hook)


def _write_packaging_loadgroup_probe(probe_root: Path) -> Path:
    production_conftest = run_packaging_tests.BACKEND_ROOT / "packaging" / "tests" / "conftest.py"
    (probe_root / "conftest.py").write_text(
        f"""
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "xpj_nested_packaging_conftest",
    {str(production_conftest)!r},
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
pytest_configure = _module.pytest_configure
pytest_collection_modifyitems = _module.pytest_collection_modifyitems
""",
        encoding="utf-8",
    )
    test_file = probe_root / "test_loadgroup.py"
    test_file.write_text(
        """
import os
from pathlib import Path

import pytest


def _record(name: str) -> None:
    root = Path(os.environ["XPJ_LOADGROUP_PROBE"])
    (root / name).write_text(os.environ["PYTEST_XDIST_WORKER"], encoding="utf-8")


@pytest.mark.packaging_resource("windows_host")
def test_windows_host() -> None:
    _record("windows-host.txt")


@pytest.mark.packaging_resource("postgres_cluster")
def test_postgres_cluster() -> None:
    _record("postgres-cluster.txt")
""",
        encoding="utf-8",
    )
    return test_file


def _run_packaging_loadgroup_probe(
    test_file: Path,
    probe_root: Path,
) -> subprocess.CompletedProcess[str]:
    environment = pytest_execution_environment(remove_keys=(run_packaging_tests.STRICT_WINDOWS_RUNTIME_ENV,))
    environment["XPJ_LOADGROUP_PROBE"] = str(probe_root)
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "--rootdir",
        str(probe_root),
        "-q",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-p",
        "xdist.plugin",
        "-n",
        "2",
        "--dist=loadgroup",
        "--max-worker-restart=0",
        "-o",
        "addopts=",
    ]
    return subprocess.run(
        command,
        cwd=run_packaging_tests.BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )


def test_packaging_loadgroup_serializes_shared_network_resources(
    tmp_path: Path,
) -> None:
    assert packaging_xdist_group("windows_host") == packaging_xdist_group("postgres_cluster")
    probe_root = tmp_path / "loadgroup-probe"
    probe_root.mkdir()
    test_file = _write_packaging_loadgroup_probe(probe_root)
    completed = _run_packaging_loadgroup_probe(test_file, probe_root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    command = list(completed.args)
    rootdir_index = command.index("--rootdir")
    assert command[rootdir_index + 1] == str(probe_root)
    worker_ids = {
        (probe_root / name).read_text(encoding="utf-8") for name in ("windows-host.txt", "postgres-cluster.txt")
    }
    assert len(worker_ids) == 1
    assert next(iter(worker_ids)).startswith("gw")
