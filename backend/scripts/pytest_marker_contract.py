"""Versioned marker vocabulary shared by pytest runners and audits."""

from __future__ import annotations

PYTEST_MARKER_CONTRACT_SCHEMA_VERSION = 2

BACKEND_PARALLEL_SAFE_MARKER = "parallel_safe"
BACKEND_REAL_DB_MARKER = "real_db"
BACKEND_STATEFUL_MARKER = "stateful_serial"
BACKEND_CLUSTER_MARKER = "cluster_serial"
BACKEND_PARALLEL_MARK_EXPRESSION = f"not {BACKEND_STATEFUL_MARKER}"

PACKAGING_RESOURCE_MARKER = "packaging_resource"
PACKAGING_PARALLEL_MARKER = "packaging_parallel"
PACKAGING_SERIAL_MARKER = "packaging_serial"
PACKAGING_RESOURCE_MEMBERSHIP_MARKER_PREFIX = "packaging_resource_"
PACKAGING_RESOURCE_MEMBERSHIP_MARKERS = (
    "packaging_resource_hermetic",
    "packaging_resource_inno_toolchain",
    "packaging_resource_postgres_cluster",
    "packaging_resource_windows_fs",
    "packaging_resource_windows_host",
)


def validated_marker_memberships(value: object, *, attribute: str) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or not value
        or len(value) != len(set(value))
        or any(
            not isinstance(marker, str)
            or not marker
            or not marker.replace("_", "").isalnum()
            for marker in value
        )
    ):
        raise RuntimeError(f"pytest marker contract has invalid {attribute}")
    return value
