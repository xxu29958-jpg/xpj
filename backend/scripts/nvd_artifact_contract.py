"""Integrity contract for reusable OWASP Dependency-Check database artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

ARTIFACT_MANIFEST_NAME = "ticketbox-nvd-manifest.json"
ARTIFACT_MANIFEST_SCHEMA_VERSION = 2
NVD_DATABASE_COMPATIBILITY_VERSION = 1
PRODUCER_CONTRACT_SCHEMA_VERSION = 2
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AuditError(RuntimeError):
    """The dependency audit could not prove a safe result."""


class ArtifactError(AuditError):
    """The downloaded artifact does not contain a usable NVD database."""


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def database_payload_path(database: Path) -> Path:
    if database.is_symlink() or not database.is_dir():
        raise ArtifactError("no trusted NVD artifact is available")
    entries = list(database.rglob("*"))
    if any(entry.is_symlink() for entry in entries):
        raise ArtifactError("the NVD artifact contains a symbolic link")
    payloads = [
        path
        for path in entries
        if path.is_file() and path.name == "odc.mv.db" and path.stat().st_size > 0
    ]
    if len(payloads) != 1:
        raise ArtifactError("the NVD artifact must contain one database payload")
    return payloads[0]


def require_database_payload(database: Path) -> None:
    database_payload_path(database)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contract_file(root: Path, relative_path: str) -> Path:
    pure_path = PurePosixPath(relative_path)
    if (
        not relative_path
        or pure_path.is_absolute()
        or "\\" in relative_path
        or str(pure_path) != relative_path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise AuditError("the producer contract contains a non-canonical path")
    candidate = root.joinpath(*pure_path.parts)
    current = root
    for part in pure_path.parts:
        current = current / part
        if current.is_symlink():
            raise AuditError("the producer contract may not reference symbolic links")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise AuditError(
            "the producer contract references a file outside the repository"
        ) from exc
    if not candidate.is_file():
        raise AuditError("the producer contract references a missing file")
    return candidate


def _contract_pattern(root: Path, pattern: str) -> list[str]:
    pure_pattern = PurePosixPath(pattern)
    if (
        not pattern
        or pure_pattern.is_absolute()
        or "\\" in pattern
        or str(pure_pattern) != pattern
        or any(part in {"", ".", ".."} for part in pure_pattern.parts)
    ):
        raise AuditError("the producer contract contains a non-canonical pattern")
    matches = sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(pattern)
        if path.is_file() or path.is_symlink()
    )
    if not matches:
        raise AuditError("the producer contract pattern matched no files")
    for relative_path in matches:
        _contract_file(root, relative_path)
    return matches


def _load_producer_contract(
    repository_root: Path,
    contract: Path,
) -> tuple[Path, Path, tuple[str, ...]]:
    root = _absolute_path(repository_root)
    contract_path = _absolute_path(contract)
    if root.is_symlink() or not root.is_dir():
        raise AuditError("the producer repository root is invalid")
    try:
        contract_relative = contract_path.relative_to(root)
    except ValueError as exc:
        raise AuditError("the producer contract must be inside the repository") from exc
    contract_path = _contract_file(root, contract_relative.as_posix())
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AuditError("the producer contract is invalid") from exc
    files = payload.get("files") if isinstance(payload, dict) else None
    patterns = payload.get("patterns") if isinstance(payload, dict) else None
    schema_version = payload.get("schemaVersion") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schemaVersion", "files", "patterns"}
        or schema_version != PRODUCER_CONTRACT_SCHEMA_VERSION
        or not isinstance(files, list)
        or not files
        or any(not isinstance(path, str) for path in files)
        or files != sorted(files)
        or len(files) != len(set(files))
        or not isinstance(patterns, list)
        or any(not isinstance(pattern, str) for pattern in patterns)
        or patterns != sorted(patterns)
        or len(patterns) != len(set(patterns))
    ):
        raise AuditError("the producer contract has an invalid file inventory")

    inventory = list(files)
    for pattern in patterns:
        inventory.extend(_contract_pattern(root, pattern))
    if len(inventory) != len(set(inventory)):
        raise AuditError("the producer contract contains overlapping file inputs")
    for relative_path in files:
        _contract_file(root, relative_path)
    return contract_path, contract_relative, tuple(sorted(inventory))


def producer_contract_inputs(repository_root: Path, contract: Path) -> tuple[str, ...]:
    _contract_path, _contract_relative, inventory = _load_producer_contract(
        repository_root,
        contract,
    )
    return inventory


def producer_contract_digest(repository_root: Path, contract: Path) -> str:
    root = _absolute_path(repository_root)
    contract_path, contract_relative, inventory = _load_producer_contract(
        root,
        contract,
    )
    digest = hashlib.sha256()
    digest.update(b"ticketbox-nvd-producer-contract-v2\0")
    contract_bytes = contract_path.read_bytes()
    digest.update(contract_relative.as_posix().encode("utf-8") + b"\0")
    digest.update(len(contract_bytes).to_bytes(8, "big"))
    digest.update(contract_bytes)
    for relative_path in inventory:
        source = _contract_file(root, relative_path)
        source_bytes = source.read_bytes()
        digest.update(relative_path.encode("utf-8") + b"\0")
        digest.update(stat.S_IMODE(source.stat().st_mode).to_bytes(4, "big"))
        digest.update(len(source_bytes).to_bytes(8, "big"))
        digest.update(source_bytes)
    return digest.hexdigest()


def _require_digest(value: str, *, label: str) -> None:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise AuditError(f"the {label} is invalid")


def write_artifact_manifest(
    database: Path,
    *,
    plugin_version: str,
    contract_digest: str,
) -> None:
    _require_digest(contract_digest, label="producer contract digest")
    payload_path = database_payload_path(database)
    manifest = {
        "schemaVersion": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "databaseCompatibility": NVD_DATABASE_COMPATIBILITY_VERSION,
        "pluginVersion": plugin_version,
        "producerContractDigest": contract_digest,
        "database": {
            "path": payload_path.relative_to(database).as_posix(),
            "sha256": _sha256_file(payload_path),
        },
    }
    destination = database / ARTIFACT_MANIFEST_NAME
    temporary = database / f".{ARTIFACT_MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def require_artifact_payload(
    database: Path,
    *,
    plugin_version: str | None = None,
    contract_digest: str | None = None,
) -> None:
    if contract_digest is not None:
        _require_digest(contract_digest, label="producer contract digest")
    payload_path = database_payload_path(database)
    manifest_path = database / ARTIFACT_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ArtifactError("the NVD artifact manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ArtifactError("the NVD artifact manifest is invalid") from exc
    database_contract = manifest.get("database") if isinstance(manifest, dict) else None
    expected_path = payload_path.relative_to(database).as_posix()
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {
            "schemaVersion",
            "databaseCompatibility",
            "pluginVersion",
            "producerContractDigest",
            "database",
        }
        or manifest.get("schemaVersion") != ARTIFACT_MANIFEST_SCHEMA_VERSION
        or manifest.get("databaseCompatibility")
        != NVD_DATABASE_COMPATIBILITY_VERSION
        or not isinstance(manifest.get("pluginVersion"), str)
        or not manifest["pluginVersion"]
        or (plugin_version is not None and manifest["pluginVersion"] != plugin_version)
        or not isinstance(manifest.get("producerContractDigest"), str)
        or SHA256_PATTERN.fullmatch(manifest["producerContractDigest"]) is None
        or (
            contract_digest is not None
            and manifest["producerContractDigest"] != contract_digest
        )
        or not isinstance(database_contract, dict)
        or set(database_contract) != {"path", "sha256"}
        or database_contract.get("path") != expected_path
        or not isinstance(database_contract.get("sha256"), str)
        or SHA256_PATTERN.fullmatch(database_contract["sha256"]) is None
        or database_contract["sha256"] != _sha256_file(payload_path)
    ):
        raise ArtifactError("the NVD artifact does not match its producer contract")
