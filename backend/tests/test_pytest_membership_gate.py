from __future__ import annotations

import pytest

from scripts.packaging_pytest_contract import (
    PACKAGING_RESOURCE_MEMBERSHIP_MARKERS,
    packaging_resource_membership_marker,
)
from scripts.pytest_membership_gate import protected_pytest_membership_violations

pytestmark = pytest.mark.parallel_safe


def _exact_packaging_memberships(
    resource: str,
    *nodeids: str,
) -> dict[str, tuple[str, ...]]:
    selected = packaging_resource_membership_marker(resource)
    return {
        marker: tuple(nodeids) if marker == selected else ()
        for marker in PACKAGING_RESOURCE_MEMBERSHIP_MARKERS
    }


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
        "packaging_parallel": (),
        "packaging_serial": ("packaging/tests/test_installer.py::test_upgrade",),
        **_exact_packaging_memberships(
            "inno_toolchain",
            "packaging/tests/test_installer.py::test_upgrade",
        ),
    }
    assert protected_pytest_membership_violations(
        complete,
        complete,
        base_readable=True,
        base_required=True,
    ) == []
    legacy_base = dict(complete)
    for marker in PACKAGING_RESOURCE_MEMBERSHIP_MARKERS:
        legacy_base[marker] = ()
    assert protected_pytest_membership_violations(
        complete,
        legacy_base,
        base_readable=True,
        base_required=True,
        base_has_exact_packaging_resources=False,
    ) == []
    legacy_misclassified = protected_pytest_membership_violations(
        complete,
        legacy_base,
        base_readable=True,
        base_required=True,
        base_has_exact_packaging_resources=True,
    )
    assert any(
        "base exact packaging resource memberships do not partition" in item
        for item in legacy_misclassified
    )
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
    packaging_incomplete = dict(complete)
    packaging_incomplete["packaging_serial"] = ()
    packaging_violations = protected_pytest_membership_violations(
        packaging_incomplete,
        complete,
        base_readable=True,
        base_required=True,
    )
    assert any(
        "not the exact packaging_all partition" in violation
        for violation in packaging_violations
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
        "packaging_parallel": (),
        "packaging_serial": ("packaging/tests/test_installer.py::test_upgrade",),
        **_exact_packaging_memberships(
            "inno_toolchain",
            "packaging/tests/test_installer.py::test_upgrade",
        ),
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

    packaging_current = dict(base)
    packaging_current["packaging_all"] = (
        *base["packaging_all"],
        "packaging/tests/test_new.py::test_new",
    )
    packaging_violations = protected_pytest_membership_violations(
        packaging_current,
        base,
        base_readable=True,
        base_required=True,
    )
    assert any("lack an explicit resource class" in item for item in packaging_violations)

    demoted = dict(base)
    demoted["packaging_parallel"] = base["packaging_serial"]
    demoted["packaging_serial"] = ()
    demotion_violations = protected_pytest_membership_violations(
        demoted,
        base,
        base_readable=True,
        base_required=True,
    )
    assert any("packaging_serial removed 1" in item for item in demotion_violations)

    resource_swapped = dict(base)
    resource_swapped[packaging_resource_membership_marker("inno_toolchain")] = ()
    resource_swapped[packaging_resource_membership_marker("windows_fs")] = base[
        packaging_resource_membership_marker("inno_toolchain")
    ]
    resource_violations = protected_pytest_membership_violations(
        resource_swapped,
        base,
        base_readable=True,
        base_required=True,
        base_has_exact_packaging_resources=True,
    )
    assert any(
        "packaging_resource_inno_toolchain removed 1" in item
        for item in resource_violations
    )
