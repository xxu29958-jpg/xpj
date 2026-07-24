"""Run the always-on CI contract suite as a closed, non-skippable lane."""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT_TESTS = BACKEND_ROOT / "tests" / "ci_contracts"


class _RejectNonPassReports:
    def __init__(self) -> None:
        self.violations: set[str] = set()

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.violations.add(report.nodeid or "<collection>")

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.skipped or hasattr(report, "wasxfail"):
            self.violations.add(report.nodeid)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(
        self,
        session: pytest.Session,
        exitstatus: int | pytest.ExitCode,
    ) -> None:
        del exitstatus
        if not self.violations:
            return
        for nodeid in sorted(self.violations):
            print(f"CI contract test did not pass: {nodeid}", file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _validate_contract_tree(contract_tests: pathlib.Path) -> None:
    if not contract_tests.is_dir():
        raise ValueError(f"CI contract test directory is missing: {contract_tests}")
    conftests = sorted(contract_tests.rglob("conftest.py"))
    if conftests:
        names = ", ".join(path.relative_to(contract_tests).as_posix() for path in conftests)
        raise ValueError(
            "CI contract tests are hermetic and cannot define conftest.py: " + names
        )


def run_contract_tests(contract_tests: pathlib.Path = CONTRACT_TESTS) -> int:
    _validate_contract_tree(contract_tests)
    previous_autoload = os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    backend_import_root = str(BACKEND_ROOT)
    added_import_root = backend_import_root not in sys.path
    if added_import_root:
        sys.path.insert(0, backend_import_root)
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        return int(
            pytest.main(
                [
                    "-q",
                    str(contract_tests),
                    "--noconftest",
                    "--strict-config",
                    "--strict-markers",
                    "-o",
                    "addopts=",
                    "-p",
                    "no:cacheprovider",
                ],
                plugins=[_RejectNonPassReports()],
            )
        )
    finally:
        if previous_autoload is None:
            os.environ.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        else:
            os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = previous_autoload
        if added_import_root:
            sys.path.remove(backend_import_root)


def main() -> int:
    if len(sys.argv) != 1:
        print("run_ci_contract_tests.py does not accept target overrides", file=sys.stderr)
        return 2
    try:
        return run_contract_tests()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
