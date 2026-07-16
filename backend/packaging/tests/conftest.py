from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from scripts.pytest_execution_contract import (
    PYTEST_EXPECTED_COUNT_ENV,
    PYTEST_EXPECTED_DIGEST_ENV,
    PYTEST_HANDSHAKE_PATH_ENV,
    PYTEST_HANDSHAKE_TOKEN_ENV,
)
from scripts.pytest_execution_contract import (
    pytest_execution_handshake_payload as execution_handshake_payload,
)
from scripts.pytest_execution_contract import (
    pytest_execution_membership_violation as execution_membership_violation,
)
from scripts.test_pg_contract import start_windows_parent_watchdog

_STRICT_RUNTIME_ENV = "XPJ_REQUIRE_WINDOWS_LIFECYCLE_RUNTIME"
_PACKAGING_TESTS_ROOT = Path(__file__).resolve().parent
def _strict_runtime_enabled() -> bool:
    return os.environ.get(_STRICT_RUNTIME_ENV) == "1"


def pytest_configure(config: pytest.Config) -> None:
    if not _strict_runtime_enabled():
        return
    start_windows_parent_watchdog(label="strict packaging pytest")
    violations: list[str] = []
    if config.getoption("collectonly", default=False):
        violations.append("strict packaging contracts must execute, not only collect")
    if len(config.args) != 1:
        violations.append("strict packaging contracts must collect the complete root")
    else:
        try:
            collection_root = Path(config.args[0]).resolve()
        except OSError:
            collection_root = Path()
        if collection_root != _PACKAGING_TESTS_ROOT:
            violations.append("strict packaging contracts must collect the complete root")
    if (
        (config.getoption("keyword", default="") or "").strip()
        or (config.getoption("markexpr", default="") or "").strip()
        or config.getoption("deselect", default=())
        or config.getoption("ignore", default=())
        or config.getoption("ignore_glob", default=())
        or config.getoption("lf", default=False)
        or sys.flags.optimize
    ):
        violations.append("strict packaging contracts must not filter the test set")
    handshake_path = os.environ.get(PYTEST_HANDSHAKE_PATH_ENV)
    handshake_token = os.environ.get(PYTEST_HANDSHAKE_TOKEN_ENV)
    if (
        not handshake_path
        or not handshake_token
        or not os.environ.get(PYTEST_EXPECTED_COUNT_ENV)
        or not os.environ.get(PYTEST_EXPECTED_DIGEST_ENV)
    ):
        violations.append("strict packaging contracts are missing execution proof inputs")
    elif Path(handshake_path).exists():
        violations.append("strict packaging completion handshake already exists")
    if violations:
        raise pytest.UsageError(" | ".join(violations))


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    items: list[pytest.Item],
) -> Generator[None, None, None]:
    yield
    if not _strict_runtime_enabled():
        return
    violation = execution_membership_violation(
        label="packaging",
        selected_nodeids=tuple(item.nodeid for item in items),
        expected_count=os.environ.get(PYTEST_EXPECTED_COUNT_ENV),
        expected_digest=os.environ.get(PYTEST_EXPECTED_DIGEST_ENV),
    )
    if violation:
        raise pytest.UsageError(violation)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Require every independently collected packaging proof to pass normally."""

    if not _strict_runtime_enabled():
        return
    terminal = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = sorted(
        {
            report.nodeid
            for report in (() if terminal is None else terminal.stats.get("skipped", ()))
        }
    )
    violations: list[str] = []
    if sys.platform != "win32":
        violations.append("strict Windows lifecycle contracts require a Windows runner")
    if skipped:
        violations.append(
            f"strict packaging contracts skipped {len(skipped)} collection or test report(s): "
            + ", ".join(skipped[:3])
        )
    forbidden = {
        name: len(terminal.stats.get(name, ()))
        for name in ("xfailed", "xpassed")
        if terminal is not None and terminal.stats.get(name)
    }
    if forbidden:
        violations.append(
            "strict packaging contracts forbid tolerated outcomes: "
            + ", ".join(f"{name}={count}" for name, count in forbidden.items())
        )
    passed_count = len(terminal.stats.get("passed", ())) if terminal is not None else None
    if (
        exitstatus != pytest.ExitCode.OK
        or passed_count is None
        or session.testscollected <= 0
        or passed_count != session.testscollected
    ):
        violations.append("strict packaging contracts did not complete every collected test normally")
    if violations:
        if terminal is not None:
            terminal.write_sep("!", " | ".join(violations), red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        return

    handshake_path = Path(os.environ[PYTEST_HANDSHAKE_PATH_ENV])
    try:
        with handshake_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(
                execution_handshake_payload(
                    "packaging",
                    os.environ[PYTEST_HANDSHAKE_TOKEN_ENV],
                    int(os.environ[PYTEST_EXPECTED_COUNT_ENV]),
                    os.environ[PYTEST_EXPECTED_DIGEST_ENV],
                )
            )
    except OSError:
        if terminal is not None:
            terminal.write_sep(
                "!",
                "strict packaging contracts could not create their completion handshake",
                red=True,
            )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
