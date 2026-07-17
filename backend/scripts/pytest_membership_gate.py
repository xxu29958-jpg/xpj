"""Fail-closed policy for protected backend and packaging pytest memberships."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

PROTECTED_PYTEST_MEMBERSHIPS = (
    "backend_all",
    "backend_parallel",
    "parallel_safe",
    "real_db",
    "stateful_serial",
    "cluster_serial",
    "packaging_all",
    "packaging_parallel",
    "packaging_serial",
)


def _membership_duplicates(nodeids: Sequence[str]) -> list[str]:
    return sorted(nodeid for nodeid, count in Counter(nodeids).items() if count > 1)


def _snapshot_shape_violations(
    snapshot: Mapping[str, Sequence[str]],
    *,
    label: str,
) -> list[str]:
    expected = set(PROTECTED_PYTEST_MEMBERSHIPS)
    violations: list[str] = []
    missing = sorted(expected - set(snapshot))
    unexpected = sorted(set(snapshot) - expected)
    if missing:
        violations.append(f"{label} snapshot is missing membership(s): " + ", ".join(missing))
    if unexpected:
        violations.append(f"{label} snapshot has unexpected membership(s): " + ", ".join(unexpected))
    for marker in sorted(expected & set(snapshot)):
        duplicates = _membership_duplicates(snapshot[marker])
        if duplicates:
            violations.append(f"{label} {marker} membership contains duplicate nodeid(s): " + ", ".join(duplicates[:3]))
    return violations


def _partition_violation(
    snapshot: Mapping[str, Sequence[str]],
    *,
    label: str,
    all_membership: str = "backend_all",
    parallel_membership: str = "backend_parallel",
    serial_membership: str = "stateful_serial",
) -> str | None:
    required = {all_membership, parallel_membership, serial_membership}
    if not required <= set(snapshot):
        return None
    partition = Counter(snapshot[parallel_membership]) + Counter(snapshot[serial_membership])
    if partition == Counter(snapshot[all_membership]):
        return None
    return (
        f"{label}{parallel_membership} plus {serial_membership} is not the exact "
        f"{all_membership} partition"
    )


def _current_invariant_violations(
    current: Mapping[str, Sequence[str]],
) -> list[str]:
    violations: list[str] = []
    if {"real_db", "stateful_serial"} <= set(current):
        missing = sorted(set(current["stateful_serial"]) - set(current["real_db"]))
        if missing:
            violations.append(
                "stateful_serial membership is not a subset of real_db: "
                + ", ".join(missing[:3])
            )
    if {"stateful_serial", "cluster_serial"} <= set(current):
        missing = sorted(set(current["cluster_serial"]) - set(current["stateful_serial"]))
        if missing:
            violations.append(
                "cluster_serial membership is not a subset of stateful_serial: "
                + ", ".join(missing[:3])
            )
    if {"parallel_safe", "real_db"} <= set(current):
        conflicting = sorted(set(current["parallel_safe"]) & set(current["real_db"]))
        if conflicting:
            violations.append(
                "parallel_safe and real_db memberships overlap: "
                + ", ".join(conflicting[:3])
            )
    partition = _partition_violation(current, label="")
    if partition:
        violations.append(partition)
    packaging_partition = _partition_violation(
        current,
        label="",
        all_membership="packaging_all",
        parallel_membership="packaging_parallel",
        serial_membership="packaging_serial",
    )
    if packaging_partition:
        violations.append(packaging_partition)
    return violations


def _new_test_classification_violations(
    current: Mapping[str, Sequence[str]],
    base: Mapping[str, Sequence[str]],
) -> list[str]:
    violations: list[str] = []
    backend_required = {"backend_all", "parallel_safe", "real_db"}
    if backend_required <= set(current) and "backend_all" in base:
        new_nodeids = set(current["backend_all"]) - set(base["backend_all"])
        classified = set(current["parallel_safe"]) | set(current["real_db"])
        unclassified = sorted(new_nodeids - classified)
        if unclassified:
            violations.append(
                "new backend test nodeid(s) lack an explicit PostgreSQL resource class: "
                + ", ".join(unclassified[:3])
            )
    packaging_required = {
        "packaging_all",
        "packaging_parallel",
        "packaging_serial",
    }
    if packaging_required <= set(current) and "packaging_all" in base:
        new_nodeids = set(current["packaging_all"]) - set(base["packaging_all"])
        classified = set(current["packaging_parallel"]) | set(current["packaging_serial"])
        unclassified = sorted(new_nodeids - classified)
        if unclassified:
            violations.append(
                "new packaging test nodeid(s) lack an explicit resource class: "
                + ", ".join(unclassified[:3])
            )
    return violations


def _removed_membership_violations(
    current: Mapping[str, Sequence[str]],
    base: Mapping[str, Sequence[str]],
) -> list[str]:
    violations: list[str] = []
    for membership in sorted(set(PROTECTED_PYTEST_MEMBERSHIPS) & set(base) & set(current)):
        removed = set(base[membership]) - set(current[membership])
        if membership == "backend_parallel":
            removed -= set(current["stateful_serial"])
        if membership == "parallel_safe":
            removed -= set(current["real_db"])
        if membership == "packaging_parallel":
            removed -= set(current["packaging_serial"])
        ordered = sorted(removed)
        if ordered:
            violations.append(
                f"{membership} removed {len(ordered)} protected test nodeid(s): "
                + ", ".join(ordered[:3])
            )
    return violations


def protected_pytest_membership_violations(
    current: Mapping[str, Sequence[str]],
    base: Mapping[str, Sequence[str]],
    *,
    base_readable: bool,
    base_required: bool,
) -> list[str]:
    """Protect committed risk proofs from removal, swapping, or lane demotion."""

    violations = _snapshot_shape_violations(current, label="current")
    violations.extend(_current_invariant_violations(current))
    if not base_readable:
        if base_required:
            violations.append("required base pytest membership snapshot is unreadable")
        return violations
    violations.extend(_snapshot_shape_violations(base, label="base"))
    base_partition = _partition_violation(base, label="base ")
    if base_partition:
        violations.append(base_partition)
    if base.get("packaging_parallel") or base.get("packaging_serial"):
        base_packaging_partition = _partition_violation(
            base,
            label="base ",
            all_membership="packaging_all",
            parallel_membership="packaging_parallel",
            serial_membership="packaging_serial",
        )
        if base_packaging_partition:
            violations.append(base_packaging_partition)
    violations.extend(_new_test_classification_violations(current, base))
    violations.extend(_removed_membership_violations(current, base))
    return violations


def evaluate_protected_pytest_memberships(
    current: Mapping[str, Sequence[str]],
    base: Mapping[str, Sequence[str]],
    *,
    base_readable: bool,
    base_required: bool,
    base_error: str | None,
) -> int:
    """Fail closed when a committed pytest risk proof disappears or is demoted."""

    print("== Gate. Protected pytest membership ==")
    violations = protected_pytest_membership_violations(
        current,
        base,
        base_readable=base_readable,
        base_required=base_required,
    )
    if violations:
        print(
            "FAIL: protected pytest risk membership drifted. Adding tests is allowed; "
            "removal, rename, or lane demotion requires a dedicated risk migration:"
        )
        for violation in violations:
            print(f"  - {violation}")
        if base_error:
            print(f"  - base_error={base_error}")
        print()
        return 1
    if not base_readable:
        print(
            "INFO: base pytest membership is unavailable in local development; "
            "exact CI context fails closed instead of skipping."
        )
    else:
        protected_count = sum(len(base[membership]) for membership in PROTECTED_PYTEST_MEMBERSHIPS)
        print(f"OK: {protected_count} committed pytest memberships remain protected.")
    print()
    return 0
