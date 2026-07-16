"""Reusable examples for protected pytest membership gate tests."""

from __future__ import annotations

import importlib


def assert_protected_pytest_membership_gate() -> None:
    gate = importlib.reload(importlib.import_module("pytest_membership_gate"))
    base = {
        "backend_all": (
            "tests/test_auth.py::test_authorized",
            "tests/test_db.py::test_commit",
            "tests/test_db.py::test_schema",
        ),
        "backend_parallel": (
            "tests/test_auth.py::test_authorized",
            "tests/test_db.py::test_commit",
        ),
        "parallel_safe": ("tests/test_auth.py::test_authorized",),
        "real_db": (
            "tests/test_db.py::test_commit",
            "tests/test_db.py::test_schema",
        ),
        "stateful_serial": ("tests/test_db.py::test_schema",),
        "cluster_serial": ("tests/test_db.py::test_schema",),
        "packaging_all": ("packaging/tests/test_installer.py::test_upgrade",),
    }
    assert (
        gate.protected_pytest_membership_violations(
            base,
            base,
            base_readable=True,
            base_required=True,
        )
        == []
    )
    swapped = {
        "backend_all": (
            "tests/test_auth.py::test_replacement",
            "tests/test_db.py::test_commit",
            "tests/test_db.py::test_replacement",
        ),
        "backend_parallel": (
            "tests/test_auth.py::test_replacement",
            "tests/test_db.py::test_commit",
        ),
        "parallel_safe": ("tests/test_auth.py::test_replacement",),
        "real_db": (
            "tests/test_db.py::test_commit",
            "tests/test_db.py::test_replacement",
        ),
        "stateful_serial": ("tests/test_db.py::test_replacement",),
        "cluster_serial": ("tests/test_db.py::test_replacement",),
        "packaging_all": ("packaging/tests/test_installer.py::test_replacement",),
    }
    violations = gate.protected_pytest_membership_violations(
        swapped,
        base,
        base_readable=True,
        base_required=True,
    )
    assert any("backend_all removed 2" in violation for violation in violations)
    assert any("backend_parallel removed 1" in violation for violation in violations)
    assert any("parallel_safe removed 1" in violation for violation in violations)
    assert any("real_db removed 1" in violation for violation in violations)
    assert any("stateful_serial removed 1" in violation for violation in violations)
    assert any("cluster_serial removed 1" in violation for violation in violations)
    assert any("packaging_all removed 1" in violation for violation in violations)
    assert gate.protected_pytest_membership_violations(
        base,
        {},
        base_readable=False,
        base_required=True,
    ) == ["required base pytest membership snapshot is unreadable"]
