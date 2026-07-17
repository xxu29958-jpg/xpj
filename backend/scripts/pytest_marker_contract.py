"""Versioned marker vocabulary shared by pytest runners and audits."""

from __future__ import annotations

PYTEST_MARKER_CONTRACT_SCHEMA_VERSION = 1

BACKEND_PARALLEL_SAFE_MARKER = "parallel_safe"
BACKEND_REAL_DB_MARKER = "real_db"
BACKEND_STATEFUL_MARKER = "stateful_serial"
BACKEND_CLUSTER_MARKER = "cluster_serial"
BACKEND_PARALLEL_MARK_EXPRESSION = f"not {BACKEND_STATEFUL_MARKER}"

PACKAGING_RESOURCE_MARKER = "packaging_resource"
PACKAGING_PARALLEL_MARKER = "packaging_parallel"
PACKAGING_SERIAL_MARKER = "packaging_serial"
