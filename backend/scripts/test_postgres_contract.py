"""Validated reader for the cross-runtime test PostgreSQL contract."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

CONTRACT_PATH = Path(__file__).with_name("test_postgres_contract.json")
_DATABASE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
_MARKER = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}")
_MARKER_FILE = re.compile(r"\.[a-z0-9][a-z0-9._-]{0,62}")
_ROOT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")


@dataclass(frozen=True)
class TestPostgresPorts:
    gitea: int
    local: int

    def for_profile(self, profile: str) -> int:
        try:
            return getattr(self, profile)
        except AttributeError as exc:
            raise ValueError(f"unknown test PostgreSQL port profile: {profile}") from exc


@dataclass(frozen=True)
class TestPostgresContract:
    application_role: str
    base_database: str
    smoke_database: str
    restore_database: str
    cluster_marker: str
    worker_marker_prefix: str
    ownership_marker_name: str
    deletion_marker_name: str
    credential_name: str
    passfile_name: str
    runtime_root_name: str
    runtime_parent: str
    ports: TestPostgresPorts
    forbidden_host_ports: frozenset[int]

    def require_allowed_host_port(self, port: object) -> int:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("test PostgreSQL requires an explicit TCP port")
        if port in self.forbidden_host_ports:
            raise ValueError("refusing a host port reserved outside the test topology")
        return port

    def runtime_root(self) -> Path:
        return _os_runtime_parent(self.runtime_parent) / self.runtime_root_name

    def default_data_dir(self, port: int) -> Path:
        return self.runtime_root() / f"xpj_pg_test{port}"

    def database_identity(self, nonce: str) -> str:
        try:
            parsed = uuid.UUID(nonce)
        except (ValueError, AttributeError) as exc:
            raise ValueError("test PostgreSQL cluster nonce must be a UUID") from exc
        if parsed.int == 0 or str(parsed) != nonce.lower():
            raise ValueError("test PostgreSQL cluster nonce is not canonical")
        return f"{self.cluster_marker}:{parsed}"

    def require_database_identity(self, value: str | None) -> str:
        prefix = f"{self.cluster_marker}:"
        if value is None or not value.startswith(prefix):
            raise ValueError("test PostgreSQL cluster identity is unavailable")
        return self.database_identity(value[len(prefix) :])

    def local_database_identity(self, port: int) -> str:
        data_dir = self.default_data_dir(self.require_allowed_host_port(port))
        marker_path = data_dir / self.ownership_marker_name
        marker_stat = marker_path.lstat()
        if marker_path.is_symlink() or not stat.S_ISREG(marker_stat.st_mode):
            raise RuntimeError("local test PostgreSQL ownership marker is not a regular file")
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
        expected_fields = {
            "schema_version",
            "data_dir",
            "cluster_marker",
            "instance_id",
            "postgres_bin",
        }
        if not isinstance(payload, dict) or set(payload) != expected_fields:
            raise RuntimeError("local test PostgreSQL ownership marker fields are invalid")
        if payload.get("schema_version") != 2 or payload.get("cluster_marker") != self.cluster_marker:
            raise RuntimeError("local test PostgreSQL ownership marker contract is invalid")
        stored_data_dir = payload.get("data_dir")
        if not isinstance(stored_data_dir, str) or os.path.normcase(os.path.abspath(stored_data_dir)) != os.path.normcase(
            os.path.abspath(data_dir)
        ):
            raise RuntimeError("local test PostgreSQL ownership marker targets another data directory")
        return self.database_identity(str(payload.get("instance_id", "")))


def _os_runtime_parent(parent: str) -> Path:
    if parent != "local_app_data":
        raise RuntimeError("unsupported test PostgreSQL runtime parent")
    if os.name != "nt":
        return Path(tempfile.gettempdir()).absolute()

    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    get_folder_path = ctypes.WinDLL("shell32", use_last_error=True).SHGetFolderPathW
    get_folder_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    )
    get_folder_path.restype = ctypes.c_long
    result = get_folder_path(None, 0x001C, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise OSError(result, "SHGetFolderPathW(CSIDL_LOCAL_APPDATA) failed")
    return Path(os.path.abspath(buffer.value))


def _required_string(raw: dict[str, object], key: str, pattern: re.Pattern[str]) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise RuntimeError(f"invalid test PostgreSQL contract field: {key}")
    return value


def load_test_postgres_contract() -> TestPostgresContract:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    expected_keys = {
        "schema_version",
        "application_role",
        "base_database",
        "smoke_database",
        "restore_database",
        "cluster_marker",
        "worker_marker_prefix",
        "ownership_marker_name",
        "deletion_marker_name",
        "credential_name",
        "passfile_name",
        "runtime_root_name",
        "runtime_parent",
        "ports",
        "forbidden_host_ports",
    }
    if not isinstance(raw, dict) or raw.get("schema_version") != 7 or set(raw) != expected_keys:
        raise RuntimeError("unsupported test PostgreSQL contract schema")
    databases = tuple(
        _required_string(raw, key, _DATABASE_NAME)
        for key in ("base_database", "smoke_database", "restore_database")
    )
    if len(set(databases)) != len(databases):
        raise RuntimeError("test PostgreSQL database roles must be distinct")
    raw_ports = raw.get("ports")
    if not isinstance(raw_ports, dict) or set(raw_ports) != {"gitea", "local"}:
        raise RuntimeError("test PostgreSQL port profiles are invalid")
    ports = tuple(raw_ports[profile] for profile in ("gitea", "local"))
    if any(not isinstance(port, int) or not 1024 <= port <= 65535 for port in ports):
        raise RuntimeError("test PostgreSQL ports must be unprivileged TCP ports")
    if len(set(ports)) != len(ports):
        raise RuntimeError("test PostgreSQL port profiles must be distinct")
    forbidden_host_ports = raw.get("forbidden_host_ports")
    if (
        not isinstance(forbidden_host_ports, list)
        or not forbidden_host_ports
        or any(
            not isinstance(port, int) or not 1024 <= port <= 65535
            for port in forbidden_host_ports
        )
        or len(set(forbidden_host_ports)) != len(forbidden_host_ports)
        or set(forbidden_host_ports) & set(ports)
    ):
        raise RuntimeError("test PostgreSQL forbidden host ports are invalid")
    return TestPostgresContract(
        application_role=_required_string(raw, "application_role", _DATABASE_NAME),
        base_database=databases[0],
        smoke_database=databases[1],
        restore_database=databases[2],
        cluster_marker=_required_string(raw, "cluster_marker", _MARKER),
        worker_marker_prefix=_required_string(raw, "worker_marker_prefix", _MARKER),
        ownership_marker_name=_required_string(raw, "ownership_marker_name", _MARKER_FILE),
        deletion_marker_name=_required_string(raw, "deletion_marker_name", _MARKER_FILE),
        credential_name=_required_string(raw, "credential_name", _MARKER_FILE),
        passfile_name=_required_string(raw, "passfile_name", _MARKER_FILE),
        runtime_root_name=_required_string(raw, "runtime_root_name", _ROOT_NAME),
        runtime_parent=_required_string(raw, "runtime_parent", _ROOT_NAME),
        ports=TestPostgresPorts(*ports),
        forbidden_host_ports=frozenset(forbidden_host_ports),
    )


TEST_POSTGRES_CONTRACT = load_test_postgres_contract()
