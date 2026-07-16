from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_packaging_tests
from scripts.pytest_execution_contract import (
    PytestCollectionSnapshot,
    parse_pytest_collection,
    pytest_execution_environment,
    pytest_execution_membership_violation,
    pytest_nodeid_digest,
)

pytestmark = pytest.mark.parallel_safe


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
            "XPJ_TEST_RUNNER_LANE": "parallel",
            "XPJ_PYTEST_EXECUTION_EXPECTED_COUNT": "1",
            "KEEP": "yes",
        }
    )

    assert environment == {
        "KEEP": "yes",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


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


def test_packaging_runner_clears_filters_and_requires_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = PytestCollectionSnapshot(("packaging/tests/test_installer.py::test_upgrade",))
    observed: dict[str, object] = {}
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only -k version")
    monkeypatch.setenv("PYTEST_PLUGINS", "ambient_plugin")
    monkeypatch.setenv("PYTHONPATH", "ambient-import-root")
    monkeypatch.setattr(
        run_packaging_tests,
        "collect_pytest_snapshot",
        lambda *args, **kwargs: snapshot,
    )

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
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert "PYTEST_ADDOPTS" not in environment
    assert "PYTEST_PLUGINS" not in environment
    assert "PYTHONPATH" not in environment
    assert environment[run_packaging_tests.STRICT_WINDOWS_RUNTIME_ENV] == "1"
    assert observed["cwd"] == run_packaging_tests.BACKEND_ROOT
    assert "-o" in observed["command"]


def test_packaging_runner_rejects_success_without_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_packaging_tests,
        "collect_pytest_snapshot",
        lambda *args, **kwargs: PytestCollectionSnapshot(("packaging/tests/test_installer.py::test_upgrade",)),
    )
    monkeypatch.setattr(
        run_packaging_tests.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    assert run_packaging_tests.run_packaging_tests() == run_packaging_tests.HANDSHAKE_FAILURE_EXIT_CODE


def test_packaging_strict_runtime_rejects_module_level_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conftest_path = (
        run_packaging_tests.BACKEND_ROOT / "packaging" / "tests" / "conftest.py"
    )
    spec = importlib.util.spec_from_file_location("xpj_packaging_conftest_probe", conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(module._STRICT_RUNTIME_ENV, "1")  # noqa: SLF001

    class Terminal:
        stats = {
            "passed": (SimpleNamespace(nodeid="packaging/tests/test_ok.py::test_ok"),),
            "skipped": (SimpleNamespace(nodeid="packaging/tests/test_optional.py"),),
        }

        def write_sep(self, *_args, **_kwargs) -> None:
            return None

    terminal = Terminal()
    session = SimpleNamespace(
        config=SimpleNamespace(
            pluginmanager=SimpleNamespace(get_plugin=lambda _name: terminal)
        ),
        testscollected=1,
        exitstatus=pytest.ExitCode.OK,
    )

    module.pytest_sessionfinish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
