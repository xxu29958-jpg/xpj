"""Reusable examples for protected pytest membership gate tests."""

from __future__ import annotations

import importlib

from scripts.packaging_pytest_contract import (
    PACKAGING_RESOURCE_MEMBERSHIP_MARKERS,
    packaging_resource_membership_marker,
)


def _exact_packaging_memberships(
    resource: str,
    nodeid: str,
) -> dict[str, tuple[str, ...]]:
    selected = packaging_resource_membership_marker(resource)
    return {
        marker: (nodeid,) if marker == selected else ()
        for marker in PACKAGING_RESOURCE_MEMBERSHIP_MARKERS
    }


def _membership_snapshot(*, replacement: bool) -> dict[str, tuple[str, ...]]:
    auth = (
        "tests/test_auth.py::test_replacement"
        if replacement
        else "tests/test_auth.py::test_authorized"
    )
    schema = (
        "tests/test_db.py::test_replacement"
        if replacement
        else "tests/test_db.py::test_schema"
    )
    package = (
        "packaging/tests/test_installer.py::test_replacement"
        if replacement
        else "packaging/tests/test_installer.py::test_upgrade"
    )
    commit = "tests/test_db.py::test_commit"
    return {
        "backend_all": (
            auth,
            commit,
            schema,
        ),
        "backend_parallel": (
            auth,
            commit,
        ),
        "parallel_safe": (auth,),
        "real_db": (commit, schema),
        "stateful_serial": (schema,),
        "cluster_serial": (schema,),
        "packaging_all": (package,),
        "packaging_parallel": (),
        "packaging_serial": (package,),
        **_exact_packaging_memberships("inno_toolchain", package),
    }


def assert_protected_pytest_membership_gate() -> None:
    gate = importlib.reload(importlib.import_module("pytest_membership_gate"))
    base = _membership_snapshot(replacement=False)
    assert (
        gate.protected_pytest_membership_violations(
            base,
            base,
            base_readable=True,
            base_required=True,
        )
        == []
    )
    swapped = _membership_snapshot(replacement=True)
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
    assert any("packaging_serial removed 1" in violation for violation in violations)
    assert gate.protected_pytest_membership_violations(
        base,
        {},
        base_readable=False,
        base_required=True,
    ) == ["required base pytest membership snapshot is unreadable"]
