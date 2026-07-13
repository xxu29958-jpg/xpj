"""Create a support-safe Desktop Manager diagnostic bundle."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import platform
import re
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend_manager.version_contract import is_managed_release_version

_MANIFEST_NAME = "BUILD_PROVENANCE.json"
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_MANIFEST_FILES = 10_000
_DOWNLOADS_FOLDER_ID = UUID("374de290-123f-4565-9164-39c4925e467b")
_UTC_TIMESTAMP_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z\Z")
_SOURCE_KEYS = frozenset({"algorithm", "fingerprint", "files"})
_MANAGER_MANIFEST_KEYS = frozenset(
    {"schema_version", "artifact_type", "version", "generated_at_utc", "toolchain", "source", "payload"},
)
_BACKEND_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "backend_version",
        "generated_at_utc",
        "toolchain",
        "source",
        "payload",
    },
)
_STARTUP_FAILURE_CODES = frozenset(
    {
        "installation_missing",
        "manager_config_invalid",
        "registry_contract_invalid",
        "release_contract_invalid",
        "runtime_config_invalid",
        "service_contract_invalid",
    },
)
_STARTUP_FAILURE_STAGES = frozenset({"runtime_discovery"})


class DiagnosticExportError(RuntimeError):
    """Raised when a support bundle cannot be created safely."""


@dataclass(frozen=True)
class DiagnosticBundle:
    path: Path

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class _ManifestSpec:
    slot: str
    artifact_type: str
    schema_version: int
    version_key: str
    top_level_keys: frozenset[str]


_MANIFEST_SPECS = (
    _ManifestSpec(
        slot="manager",
        artifact_type="ticketbox-frozen-desktop-manager",
        schema_version=1,
        version_key="version",
        top_level_keys=_MANAGER_MANIFEST_KEYS,
    ),
    _ManifestSpec(
        slot="backend",
        artifact_type="ticketbox-frozen-backend",
        schema_version=3,
        version_key="backend_version",
        top_level_keys=_BACKEND_MANIFEST_KEYS,
    ),
)


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: UUID) -> _Guid:
        raw = value.bytes_le
        return cls(
            int.from_bytes(raw[0:4], "little"),
            int.from_bytes(raw[4:6], "little"),
            int.from_bytes(raw[6:8], "little"),
            (ctypes.c_ubyte * 8)(*raw[8:16]),
        )


def downloads_directory() -> Path:
    """Resolve the current user's Downloads known folder without a fixed path."""
    if os.name != "nt":
        return Path.home() / "Downloads"

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_Guid),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    folder_id = _Guid.from_uuid(_DOWNLOADS_FOLDER_ID)
    raw_path = ctypes.c_wchar_p()
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(raw_path))
    if result != 0 or not raw_path.value:
        raise DiagnosticExportError("Windows 无法定位当前用户的下载文件夹。")
    try:
        return Path(raw_path.value)
    finally:
        ole32.CoTaskMemFree(raw_path)


def _manifest_paths() -> tuple[Path, ...]:
    if not getattr(sys, "frozen", False):
        return ()
    manager_dir = Path(sys.executable).resolve().parent
    return (
        manager_dir / _MANIFEST_NAME,
        manager_dir.parent / "program" / "ticketbox-backend" / _MANIFEST_NAME,
    )


def _digest_text(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        return None
    return lowered


def _matched_text(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _payload_record(value: object) -> tuple[str, int, str] | None:
    if not isinstance(value, dict) or set(value) != {"path", "size", "sha256"}:
        return None
    relative = value.get("path")
    size = value.get("size")
    digest = _digest_text(value.get("sha256"))
    if (
        not isinstance(relative, str)
        or not relative
        or len(relative) > 1024
        or "\\" in relative
        or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or digest is None
    ):
        return None
    return relative, size, digest


def _snapshot_fingerprint(records: list[tuple[str, int, str]]) -> str:
    value = "".join(f"{relative}\0{size}\0{digest}\n" for relative, size, digest in records)
    return hashlib.sha256(value.encode()).hexdigest()


def _source_snapshot_valid(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _SOURCE_KEYS:
        return False
    records = value.get("files")
    fingerprint = _digest_text(value.get("fingerprint"))
    if value.get("algorithm") != "SHA-256" or not isinstance(records, list) or fingerprint is None:
        return False
    parsed = [_payload_record(record) for record in records]
    if any(record is None for record in parsed):
        return False
    typed = [record for record in parsed if record is not None]
    paths = [record[0] for record in typed]
    return (
        bool(typed)
        and len(typed) <= _MAX_MANIFEST_FILES
        and len({path.casefold() for path in paths}) == len(paths)
        and _snapshot_fingerprint(typed) == fingerprint
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_integrity(manifest_path: Path, payload: object) -> tuple[str, str | None, str | None]:
    if not isinstance(payload, dict) or set(payload) != {"algorithm", "fingerprint", "files", "executable"}:
        return "manifest_invalid", None, None
    files = payload.get("files")
    fingerprint = _digest_text(payload.get("fingerprint"))
    if payload.get("algorithm") != "SHA-256" or not isinstance(files, list) or fingerprint is None:
        return "manifest_invalid", None, None
    if not files or len(files) > _MAX_MANIFEST_FILES:
        return "manifest_invalid", None, None
    records = [_payload_record(value) for value in files]
    if any(record is None for record in records):
        return "manifest_invalid", None, None
    typed_records = [record for record in records if record is not None]
    relative_paths = [record[0] for record in typed_records]
    if (
        len({path.casefold() for path in relative_paths}) != len(relative_paths)
    ):
        return "manifest_invalid", None, None

    root = manifest_path.parent
    try:
        actual_paths = {
            path.relative_to(root).as_posix().casefold()
            for path in root.rglob("*")
            if path.is_file() and path != manifest_path
        }
        if actual_paths != {path.casefold() for path in relative_paths}:
            return "mismatch", None, None
        for relative, size, digest in typed_records:
            candidate = root.joinpath(*relative.split("/"))
            if candidate.is_symlink() or candidate.stat().st_size != size or _file_sha256(candidate) != digest:
                return "mismatch", None, None
    except OSError:
        return "unreadable", None, None

    if _snapshot_fingerprint(typed_records) != fingerprint:
        return "manifest_invalid", None, None
    executable = _payload_record(payload.get("executable"))
    if executable is None or executable not in typed_records:
        return "manifest_invalid", None, None
    return "verified", fingerprint, executable[2]


def _manifest_summary(path: Path, spec: _ManifestSpec) -> dict[str, object]:
    base: dict[str, object] = {
        "slot": spec.slot,
        "manifest_state": "invalid",
        "installed_payload_integrity": "not_checked",
    }
    try:
        if not path.exists():
            return {**base, "manifest_state": "missing"}
        if not path.is_file() or path.stat().st_size > _MAX_MANIFEST_BYTES:
            return base
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {**base, "manifest_state": "unreadable"}
    except (UnicodeError, json.JSONDecodeError):
        return base
    if (
        not isinstance(payload, dict)
        or set(payload) != spec.top_level_keys
        or payload.get("schema_version") != spec.schema_version
        or payload.get("artifact_type") != spec.artifact_type
        or not is_managed_release_version(payload.get(spec.version_key))
        or _matched_text(payload.get("generated_at_utc"), _UTC_TIMESTAMP_PATTERN) is None
        or not isinstance(payload.get("toolchain"), dict)
        or not payload["toolchain"]
        or not _source_snapshot_valid(payload.get("source"))
    ):
        return base
    source = payload.get("source")
    artifact = payload.get("payload")
    integrity, payload_digest, executable_digest = _payload_integrity(path, artifact)
    if integrity == "manifest_invalid":
        return base
    summary = {
        "slot": spec.slot,
        "manifest_state": "valid",
        "artifact_type": spec.artifact_type,
        "schema_version": spec.schema_version,
        "version": payload[spec.version_key],
        "generated_at_utc": _matched_text(payload.get("generated_at_utc"), _UTC_TIMESTAMP_PATTERN),
        "recorded_source_sha256": _digest_text(source.get("fingerprint")) if isinstance(source, dict) else None,
        "installed_payload_integrity": integrity,
        "payload_sha256": payload_digest,
        "executable_sha256": executable_digest,
    }
    return {key: value for key, value in summary.items() if isinstance(value, (int, str))}


def _runtime_summary(status: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "runtime_mode",
        "running",
        "health",
        "health_state",
        "uptime_seconds",
        "auto_restart",
        "restarts",
        "backend_service_state",
        "database_service_state",
        "public_endpoint_state",
        "runtime_access_state",
        "owner_state",
        "owner_recovery_channel",
        "version",
    )
    result = {
        key: status[key]
        for key in allowed
        if key in status and isinstance(status[key], (bool, int, str))
    }
    result["control_error_present"] = bool(status.get("control_error"))
    failure_code = status.get("startup_failure_code")
    failure_stage = status.get("startup_failure_stage")
    if failure_code in _STARTUP_FAILURE_CODES:
        result["startup_failure_code"] = failure_code
    if failure_stage in _STARTUP_FAILURE_STAGES:
        result["startup_failure_stage"] = failure_stage
    return result


def _bundle_payload(status: Mapping[str, object]) -> dict[str, object]:
    paths = _manifest_paths()
    manifests = [
        _manifest_summary(path, spec)
        for path, spec in zip(paths, _MANIFEST_SPECS, strict=False)
    ]
    return {
        "schema": "ticketbox-desktop-diagnostics-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "runtime": _runtime_summary(status),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "builds": manifests,
        "privacy": {
            "contains_tokens": False,
            "contains_database_content": False,
            "contains_absolute_data_paths": False,
            "contains_raw_logs": False,
        },
    }


def export_diagnostic_bundle(
    status: Mapping[str, object],
    *,
    output_dir: Path | None = None,
    now: datetime | None = None,
) -> DiagnosticBundle:
    """Write an atomic ZIP containing only allowlisted host/runtime evidence."""
    target_dir = output_dir or downloads_directory()
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d-%H%M%S-%fZ")
    target = target_dir / f"Ticketbox-Diagnostics-{stamp}-{uuid4().hex[:8]}.zip"
    temporary = target_dir / f".{target.name}.{uuid4().hex}.tmp"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_bundle_payload(status), ensure_ascii=False, indent=2).encode("utf-8")
        readme = (
            "小票夹诊断包\r\n"
            "\r\n"
            "此文件仅包含服务状态、操作系统版本和构建摘要。\r\n"
            "不包含账号令牌、数据库内容、业务日志或本机数据绝对路径。\r\n"
        ).encode("utf-8-sig")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", payload)
            archive.writestr("README.txt", readme)
        os.link(temporary, target)
        temporary.unlink()
    except OSError as exc:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise DiagnosticExportError("诊断包写入失败，请检查下载文件夹是否可用。") from exc
    return DiagnosticBundle(path=target)
