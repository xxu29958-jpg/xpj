"""Explicit resource scheduling contracts for packaging pytest."""

from __future__ import annotations

from scripts import pytest_marker_contract

PACKAGING_RESOURCE_MARKER = pytest_marker_contract.PACKAGING_RESOURCE_MARKER

PACKAGING_HERMETIC_RESOURCE = "hermetic"
PACKAGING_SERIAL_RESOURCES = frozenset(
    {
        "inno_toolchain",
        "postgres_cluster",
        "windows_fs",
        "windows_host",
    }
)
PACKAGING_RESOURCES = frozenset({PACKAGING_HERMETIC_RESOURCE, *PACKAGING_SERIAL_RESOURCES})
_PACKAGING_XDIST_GROUP_BY_RESOURCE = {
    "inno_toolchain": "xpj-packaging-inno-toolchain",
    "postgres_cluster": "xpj-packaging-host-network",
    "windows_fs": "xpj-packaging-windows-fs",
    "windows_host": "xpj-packaging-host-network",
}


def packaging_xdist_group(resource: str) -> str:
    if resource not in PACKAGING_SERIAL_RESOURCES:
        raise ValueError(f"packaging resource is not serial: {resource!r}")
    return _PACKAGING_XDIST_GROUP_BY_RESOURCE[resource]
