from __future__ import annotations

import pytest

from scripts.pytest_membership_gate import protected_pytest_membership_violations

pytestmark = pytest.mark.parallel_safe


def test_backend_lanes_must_form_the_exact_full_membership_partition() -> None:
    complete = {
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
    incomplete = dict(complete)
    incomplete["backend_parallel"] = ("tests/test_auth.py::test_authorized",)

    violations = protected_pytest_membership_violations(
        incomplete,
        complete,
        base_readable=True,
        base_required=True,
    )

    assert any(
        "not the exact backend_all partition" in violation
        for violation in violations
    )


def test_new_backend_tests_require_one_explicit_resource_class() -> None:
    base = {
        "backend_all": ("tests/test_auth.py::test_authorized",),
        "backend_parallel": ("tests/test_auth.py::test_authorized",),
        "parallel_safe": (),
        "real_db": (),
        "stateful_serial": (),
        "cluster_serial": (),
        "packaging_all": ("packaging/tests/test_installer.py::test_upgrade",),
    }
    current = dict(base)
    current["backend_all"] = (*base["backend_all"], "tests/test_new.py::test_new")
    current["backend_parallel"] = (*base["backend_parallel"], "tests/test_new.py::test_new")

    violations = protected_pytest_membership_violations(
        current,
        base,
        base_readable=True,
        base_required=True,
    )

    assert any("lack an explicit PostgreSQL resource class" in item for item in violations)
