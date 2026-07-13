"""Validate the frozen Manager's adjacent build and payload identity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from backend_manager.version_contract import is_managed_release_version

_MANIFEST_NAME = "BUILD_PROVENANCE.json"
_ARTIFACT_TYPE = "ticketbox-frozen-desktop-manager"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_PAYLOAD_FILES = 4096
_HASH_CHUNK_BYTES = 1024 * 1024
_TOP_LEVEL_KEYS = {
    "schema_version",
    "artifact_type",
    "version",
    "generated_at_utc",
    "toolchain",
    "source",
    "payload",
}
_SNAPSHOT_KEYS = {"algorithm", "fingerprint", "files"}
_PAYLOAD_KEYS = {*_SNAPSHOT_KEYS, "executable"}
_FILE_KEYS = {"path", "size", "sha256"}


@dataclass(frozen=True)
class FrozenManagerIdentity:
    executable: Path
    version: str


@dataclass(frozen=True)
class _FileEvidence:
    path: str
    size: int
    sha256: str


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _lstat_regular_file(path: Path) -> os.stat_result | None:
    try:
        file_stat = path.lstat()
    except OSError:
        return None
    if path.is_symlink() or _is_reparse_point(file_stat) or not stat.S_ISREG(file_stat.st_mode):
        return None
    return file_stat


def _stable_file_bytes(path: Path, *, maximum_bytes: int | None = None) -> bytes | None:
    initial = _lstat_regular_file(path)
    if initial is None or (maximum_bytes is not None and initial.st_size > maximum_bytes):
        return None
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _is_reparse_point(opened):
                return None
            value = stream.read() if maximum_bytes is None else stream.read(maximum_bytes + 1)
            final_opened = os.fstat(stream.fileno())
        final_path = path.lstat()
    except OSError:
        return None
    if maximum_bytes is not None and len(value) > maximum_bytes:
        return None
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(
        getattr(initial, field, None) != getattr(opened, field, None)
        or getattr(opened, field, None) != getattr(final_opened, field, None)
        or getattr(final_opened, field, None) != getattr(final_path, field, None)
        for field in stable_fields
    ):
        return None
    return value


def _stable_sha256(path: Path, *, expected_size: int) -> str | None:
    initial = _lstat_regular_file(path)
    if initial is None or initial.st_size != expected_size:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_reparse_point(opened)
                or opened.st_size != expected_size
            ):
                return None
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
            final_opened = os.fstat(stream.fileno())
        final_path = path.lstat()
    except OSError:
        return None
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(
        getattr(initial, field, None) != getattr(opened, field, None)
        or getattr(opened, field, None) != getattr(final_opened, field, None)
        or getattr(final_opened, field, None) != getattr(final_path, field, None)
        for field in stable_fields
    ):
        return None
    return digest.hexdigest()


def _safe_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value or ":" in value:
        return None
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        return None
    return value


def _parse_file_evidence(value: Any) -> _FileEvidence | None:
    if not isinstance(value, dict) or set(value) != _FILE_KEYS:
        return None
    path = _safe_relative_path(value.get("path"))
    size = value.get("size")
    sha256 = value.get("sha256")
    if (
        path is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(sha256, str)
        or not _SHA256_PATTERN.fullmatch(sha256)
    ):
        return None
    return _FileEvidence(path=path, size=size, sha256=sha256)


def _snapshot_fingerprint(files: list[_FileEvidence]) -> str:
    value = "".join(f"{item.path}\0{item.size}\0{item.sha256}\n" for item in files)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_snapshot(value: Any, *, expected_keys: set[str]) -> list[_FileEvidence] | None:
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("algorithm") != "SHA-256"
        or not isinstance(value.get("fingerprint"), str)
        or not _SHA256_PATTERN.fullmatch(value["fingerprint"])
        or not isinstance(value.get("files"), list)
        or not 0 < len(value["files"]) <= _MAX_PAYLOAD_FILES
    ):
        return None
    files: list[_FileEvidence] = []
    names: set[str] = set()
    for raw_file in value["files"]:
        evidence = _parse_file_evidence(raw_file)
        if evidence is None or evidence.path.casefold() in names:
            return None
        names.add(evidence.path.casefold())
        files.append(evidence)
    if _snapshot_fingerprint(files) != value["fingerprint"]:
        return None
    return files


def _valid_generated_at(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _enumerate_payload(root: Path) -> set[str] | None:
    files: set[str] = set()
    pending = [root]
    try:
        while pending:
            directory = pending.pop()
            directory_stat = directory.lstat()
            if (
                directory.is_symlink()
                or _is_reparse_point(directory_stat)
                or not stat.S_ISDIR(directory_stat.st_mode)
            ):
                return None
            with os.scandir(directory) as entries:
                for entry in entries:
                    entry_stat = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or _is_reparse_point(entry_stat):
                        return None
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        relative = path.relative_to(root).as_posix()
                        if relative.casefold() != _MANIFEST_NAME.casefold():
                            files.add(relative)
                    else:
                        return None
    except (OSError, ValueError):
        return None
    return files


def _validated_identity_payload(executable: Path, payload: Any) -> bool:
    source_files = _parse_snapshot(payload.get("source"), expected_keys=_SNAPSHOT_KEYS)
    payload_value = payload.get("payload")
    payload_files = _parse_snapshot(payload_value, expected_keys=_PAYLOAD_KEYS)
    if source_files is None or payload_files is None or not isinstance(payload.get("toolchain"), dict):
        return False
    if not payload["toolchain"]:
        return False
    executable_evidence = _parse_file_evidence(payload_value.get("executable"))
    expected_executable = next(
        (item for item in payload_files if item.path.casefold() == executable.name.casefold()),
        None,
    )
    if (
        executable_evidence is None
        or expected_executable is None
        or executable_evidence != expected_executable
        or executable_evidence.path != executable.name
    ):
        return False
    root = executable.parent
    expected_paths = {item.path for item in payload_files}
    before = _enumerate_payload(root)
    if before is None or before != expected_paths:
        return False
    for evidence in payload_files:
        candidate = root.joinpath(*PurePosixPath(evidence.path).parts)
        if _stable_sha256(candidate, expected_size=evidence.size) != evidence.sha256:
            return False
    return _enumerate_payload(root) == before


def load_frozen_manager_identity() -> FrozenManagerIdentity | None:
    """Return a fully validated adjacent frozen identity, or ``None``."""
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).absolute()
    if _lstat_regular_file(executable) is None:
        return None
    manifest = executable.parent / _MANIFEST_NAME
    raw_manifest = _stable_file_bytes(manifest, maximum_bytes=_MAX_MANIFEST_BYTES)
    if raw_manifest is None:
        return None
    try:
        payload = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    version = payload.get("version") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or set(payload) != _TOP_LEVEL_KEYS
        or payload.get("schema_version") != 1
        or payload.get("artifact_type") != _ARTIFACT_TYPE
        or not is_managed_release_version(version)
        or not _valid_generated_at(payload.get("generated_at_utc"))
        or not _validated_identity_payload(executable, payload)
    ):
        return None
    return FrozenManagerIdentity(executable=executable, version=version)
