"""Explicit resource and execution contracts for packaging pytest."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

PACKAGING_RESOURCE_MARKER = "packaging_resource"
PACKAGING_PARALLEL_MARKER = "packaging_parallel"
PACKAGING_SERIAL_MARKER = "packaging_serial"

PACKAGING_HERMETIC_RESOURCE = "hermetic"
PACKAGING_SERIAL_RESOURCES = frozenset(
    {
        "inno_toolchain",
        "postgres_cluster",
        "windows_fs",
        "windows_host",
    }
)
PACKAGING_RESOURCES = frozenset(
    {PACKAGING_HERMETIC_RESOURCE, *PACKAGING_SERIAL_RESOURCES}
)
_PACKAGING_XDIST_GROUP_BY_RESOURCE = {
    "inno_toolchain": "xpj-packaging-inno-toolchain",
    "postgres_cluster": "xpj-packaging-host-network",
    "windows_fs": "xpj-packaging-windows-fs",
    "windows_host": "xpj-packaging-host-network",
}

PACKAGING_EXPECTED_PARALLEL_COUNT_ENV = (
    "XPJ_PACKAGING_PYTEST_EXPECTED_PARALLEL_COUNT"
)
PACKAGING_EXPECTED_PARALLEL_DIGEST_ENV = (
    "XPJ_PACKAGING_PYTEST_EXPECTED_PARALLEL_DIGEST"
)
PACKAGING_EXPECTED_SERIAL_COUNT_ENV = "XPJ_PACKAGING_PYTEST_EXPECTED_SERIAL_COUNT"
PACKAGING_EXPECTED_SERIAL_DIGEST_ENV = "XPJ_PACKAGING_PYTEST_EXPECTED_SERIAL_DIGEST"


def packaging_partition_violation(
    all_nodeids: Sequence[str],
    parallel_nodeids: Sequence[str],
    serial_nodeids: Sequence[str],
) -> str | None:
    """Require parallel and serial memberships to be an exact disjoint partition."""

    complete = Counter(all_nodeids)
    parallel = Counter(parallel_nodeids)
    serial = Counter(serial_nodeids)
    if (
        all(count == 1 for count in complete.values())
        and all(count == 1 for count in parallel.values())
        and all(count == 1 for count in serial.values())
        and not (set(parallel) & set(serial))
        and parallel + serial == complete
    ):
        return None
    return (
        "packaging_parallel plus packaging_serial is not the exact "
        "packaging test partition"
    )


def packaging_xdist_group(resource: str) -> str:
    if resource not in PACKAGING_SERIAL_RESOURCES:
        raise ValueError(f"packaging resource is not serial: {resource!r}")
    return _PACKAGING_XDIST_GROUP_BY_RESOURCE[resource]
