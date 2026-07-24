from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_ci_contract_tests


def test_ci_contract_runner_rejects_skip_and_xfail_reports() -> None:
    plugin = run_ci_contract_tests._RejectNonPassReports()
    plugin.pytest_runtest_logreport(
        SimpleNamespace(nodeid="test_contract.py::test_skip", skipped=True)
    )
    xfail = SimpleNamespace(
        nodeid="test_contract.py::test_xfail",
        skipped=False,
        wasxfail="known defect",
    )
    plugin.pytest_runtest_logreport(xfail)
    session = SimpleNamespace(exitstatus=pytest.ExitCode.OK)

    plugin.pytest_sessionfinish(session, pytest.ExitCode.OK)

    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
    assert plugin.violations == {
        "test_contract.py::test_skip",
        "test_contract.py::test_xfail",
    }


def test_ci_contract_runner_rejects_local_conftest(tmp_path: Path) -> None:
    contract_tests = tmp_path / "ci_contracts"
    contract_tests.mkdir()
    (contract_tests / "conftest.py").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot define conftest.py"):
        run_ci_contract_tests._validate_contract_tree(contract_tests)
