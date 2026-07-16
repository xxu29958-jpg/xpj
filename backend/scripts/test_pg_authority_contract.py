"""Owned PostgreSQL marker and generation contracts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy.engine import URL

from scripts.test_pg_protected_reader import read_protected_utf8_file
from scripts.test_pg_url_contract import (
    TEST_CLUSTER_INSTANCE_ID_ENV,
    TEST_CLUSTER_MARKER_PATH_ENV,
    TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV,
)
from scripts.test_pg_windows_contract import _database_port, _windows_temp_directory

_OWNERSHIP_MARKER_NAME = ".xpj-test-cluster.json"
_OWNERSHIP_MARKER_KIND = "xiaopiaojia-test-postgres"
_INSTANCE_ID = re.compile(r"[0-9a-f]{32}")
_SYSTEM_IDENTIFIER = re.compile(r"\d{10,20}")


def _owned_marker_candidate(
    database_url: URL,
    environment: Mapping[str, str],
) -> Path:
    configured = environment.get(TEST_CLUSTER_MARKER_PATH_ENV, "").strip()
    if configured:
        marker_path = Path(configured)
    else:
        if os.name != "nt" or environment.get("XPJ_TEST_DATABASE_URL", "").strip():
            raise RuntimeError("Owned test-cluster authority requires its marker path")
        marker_path = (
            _windows_temp_directory()
            / f"xpj_pg_test{_database_port(database_url)}"
            / _OWNERSHIP_MARKER_NAME
        )
    if not marker_path.is_absolute() or marker_path.name != _OWNERSHIP_MARKER_NAME:
        raise RuntimeError(f"Owned test-cluster marker path is invalid: {marker_path}")
    return Path(os.path.abspath(marker_path))


def _expected_cluster_generation(
    environment: Mapping[str, str],
) -> tuple[str, str]:
    system_identifier = environment.get(
        TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV,
        "",
    ).strip()
    instance_id = environment.get(TEST_CLUSTER_INSTANCE_ID_ENV, "").strip()
    if _SYSTEM_IDENTIFIER.fullmatch(system_identifier) is None:
        raise RuntimeError("Test-cluster authority is missing its system identifier")
    if _INSTANCE_ID.fullmatch(instance_id) is None:
        raise RuntimeError("Test-cluster authority is missing its instance identifier")
    return system_identifier, instance_id


def _read_owned_cluster_marker(
    database_url: URL,
    environment: Mapping[str, str],
) -> tuple[Path, str, str]:
    marker_path = _owned_marker_candidate(database_url, environment)
    try:
        payload = json.loads(
            read_protected_utf8_file(
                marker_path,
                label="Owned test-cluster marker",
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Owned test-cluster marker is unreadable: {marker_path}"
        ) from exc
    marker_port = payload.get("port")
    schema_version = payload.get("schema_version")
    instance_id = str(payload.get("instance_id", ""))
    system_identifier = str(payload.get("system_identifier", ""))
    expected_system_identifier, expected_instance_id = _expected_cluster_generation(
        environment
    )
    if (
        schema_version != 3
        or payload.get("kind") != _OWNERSHIP_MARKER_KIND
        or payload.get("purpose") not in {"local", "ci"}
        or not isinstance(marker_port, int)
        or marker_port != _database_port(database_url)
        or _INSTANCE_ID.fullmatch(instance_id) is None
        or _SYSTEM_IDENTIFIER.fullmatch(system_identifier) is None
        or payload.get("authentication") != "scram-sha-256"
    ):
        raise RuntimeError(f"Owned test-cluster marker is invalid: {marker_path}")
    if (
        system_identifier != expected_system_identifier
        or instance_id != expected_instance_id
    ):
        raise RuntimeError(
            "Owned test-cluster marker generation does not match its environment: "
            f"{marker_path}"
        )
    return marker_path.parent, system_identifier, instance_id
