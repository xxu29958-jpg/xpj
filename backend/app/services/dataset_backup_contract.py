"""Closed manifest contract for one complete Ticketbox dataset backup."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.errors import AppError
from app.services.dataset_authority_service import DatasetAuthority
from app.services.path_entry_safety import is_link_or_reparse

MANIFEST_NAME = "manifest.json"
DATABASE_ARCHIVE_NAME = "database.dump"
ORIGINALS_DIRECTORY_NAME = "originals"
MANIFEST_SCHEMA = "ticketbox-dataset-backup-v1"
MANIFEST_KIND = "ticketbox-dataset-backup"
SANITATION_POLICY = "ticketbox-restore-sanitation-v1"
BACKUP_KINDS = frozenset({"manual"})

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")
_PAYLOAD_FIELDS = frozenset(
    {
        "backup_id",
        "operation_id",
        "backup_kind",
        "created_at_utc",
        "release_id",
        "writer_fence_sha256",
        "dataset_authority",
        "database",
        "originals",
        "originals_sha256",
        "original_count",
        "original_bytes",
        "sanitation_policy",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "dataset_id",
        "client_generation",
        "restore_epoch",
        "schema_revision",
        "schema_min_compatible",
        "semantic_revision",
        "created_at_utc",
        "restored_from_backup_id",
    }
)
_DATABASE_FIELDS = frozenset({"path", "format", "size_bytes", "sha256"})
_ORIGINAL_FIELDS = frozenset({"storage_key", "size_bytes", "sha256", "tenant_ids"})


@dataclass(frozen=True)
class OriginalArtifact:
    storage_key: str
    size_bytes: int
    sha256: str
    tenant_ids: tuple[str, ...]


@dataclass(frozen=True)
class DatabaseArtifact:
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DatasetBackupManifest:
    backup_id: str
    operation_id: str
    backup_kind: str
    created_at: datetime
    release_id: str
    writer_fence_sha256: str
    authority: DatasetAuthority
    database: DatabaseArtifact
    originals: tuple[OriginalArtifact, ...]

    @property
    def total_size_bytes(self) -> int:
        return self.database.size_bytes + sum(item.size_bytes for item in self.originals)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def encode_manifest(manifest: DatasetBackupManifest) -> bytes:
    originals = [_original_payload(item) for item in manifest.originals]
    payload = {
        "backup_id": manifest.backup_id,
        "operation_id": manifest.operation_id,
        "backup_kind": manifest.backup_kind,
        "created_at_utc": _utc_text(manifest.created_at),
        "release_id": manifest.release_id,
        "writer_fence_sha256": manifest.writer_fence_sha256,
        "dataset_authority": _authority_payload(manifest.authority),
        "database": {
            "path": DATABASE_ARCHIVE_NAME,
            "format": "postgresql-custom",
            "size_bytes": manifest.database.size_bytes,
            "sha256": manifest.database.sha256,
        },
        "originals": originals,
        "originals_sha256": hashlib.sha256(canonical_json_bytes(originals)).hexdigest(),
        "original_count": len(originals),
        "original_bytes": sum(item.size_bytes for item in manifest.originals),
        "sanitation_policy": SANITATION_POLICY,
    }
    envelope = {
        "schema": MANIFEST_SCHEMA,
        "kind": MANIFEST_KIND,
        "payload_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        "payload": payload,
    }
    return canonical_json_bytes(envelope)


def read_manifest(generation_dir: Path, *, verify_files: bool) -> DatasetBackupManifest:
    manifest_path = generation_dir / MANIFEST_NAME
    try:
        raw = manifest_path.read_bytes()
        envelope = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not isinstance(envelope, dict) or set(envelope) != {
        "schema",
        "kind",
        "payload_sha256",
        "payload",
    }:
        raise AppError("backup_incomplete", status_code=500)
    payload = envelope.get("payload")
    if (
        envelope.get("schema") != MANIFEST_SCHEMA
        or envelope.get("kind") != MANIFEST_KIND
        or not isinstance(payload, dict)
        or set(payload) != _PAYLOAD_FIELDS
        or envelope.get("payload_sha256") != hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        or raw != canonical_json_bytes(envelope)
    ):
        raise AppError("backup_incomplete", status_code=500)
    manifest = _decode_payload(payload)
    if verify_files:
        _verify_artifacts(generation_dir, manifest)
    return manifest


def _decode_payload(payload: dict[str, object]) -> DatasetBackupManifest:
    authority = _decode_authority(_mapping(payload["dataset_authority"], _AUTHORITY_FIELDS))
    database = _mapping(payload["database"], _DATABASE_FIELDS)
    raw_originals = payload["originals"]
    if not isinstance(raw_originals, list):
        raise AppError("backup_incomplete", status_code=500)
    originals = tuple(_decode_original(_mapping(item, _ORIGINAL_FIELDS)) for item in raw_originals)
    storage_keys = [item.storage_key for item in originals]
    original_payloads = [_original_payload(item) for item in originals]
    if (
        payload["backup_kind"] not in BACKUP_KINDS
        or payload["sanitation_policy"] != SANITATION_POLICY
        or payload["original_count"] != len(originals)
        or payload["original_bytes"] != sum(item.size_bytes for item in originals)
        or payload["originals_sha256"] != hashlib.sha256(canonical_json_bytes(original_payloads)).hexdigest()
        or storage_keys != sorted(set(storage_keys))
        or database["path"] != DATABASE_ARCHIVE_NAME
        or database["format"] != "postgresql-custom"
    ):
        raise AppError("backup_incomplete", status_code=500)
    return DatasetBackupManifest(
        backup_id=_uuid(payload["backup_id"]),
        operation_id=_uuid(payload["operation_id"]),
        backup_kind=str(payload["backup_kind"]),
        created_at=_datetime(payload["created_at_utc"]),
        release_id=_plain_text(payload["release_id"], limit=128),
        writer_fence_sha256=_sha(payload["writer_fence_sha256"]),
        authority=authority,
        database=DatabaseArtifact(
            size_bytes=_positive_int(database["size_bytes"]),
            sha256=_sha(database["sha256"]),
        ),
        originals=originals,
    )


def _decode_authority(value: dict[str, object]) -> DatasetAuthority:
    revision = str(value["schema_revision"])
    if _REVISION.fullmatch(revision) is None:
        raise AppError("backup_incomplete", status_code=500)
    restored_from = value["restored_from_backup_id"]
    return DatasetAuthority(
        dataset_id=_uuid(value["dataset_id"]),
        client_generation=_uuid(value["client_generation"]),
        restore_epoch=_nonnegative_int(value["restore_epoch"]),
        schema_revision=revision,
        schema_min_compatible=_plain_text(value["schema_min_compatible"], limit=64),
        semantic_revision=_plain_text(value["semantic_revision"], limit=64),
        created_at=_datetime(value["created_at_utc"]),
        restored_from_backup_id=None if restored_from is None else _uuid(restored_from),
    )


def _decode_original(value: dict[str, object]) -> OriginalArtifact:
    tenants = value["tenant_ids"]
    if not isinstance(tenants, list) or tenants != sorted(set(tenants)):
        raise AppError("backup_incomplete", status_code=500)
    return OriginalArtifact(
        storage_key=_storage_key(value["storage_key"]),
        size_bytes=_positive_int(value["size_bytes"]),
        sha256=_sha(value["sha256"]),
        tenant_ids=tuple(_plain_text(item, limit=64) for item in tenants),
    )


def _verify_artifacts(generation_dir: Path, manifest: DatasetBackupManifest) -> None:
    expected = {
        DATABASE_ARCHIVE_NAME: manifest.database,
        **{item.storage_key: item for item in manifest.originals},
    }
    for relative, artifact in expected.items():
        path = (generation_dir / relative).resolve()
        try:
            path.relative_to(generation_dir.resolve())
            stat = path.stat()
        except (OSError, ValueError) as exc:
            raise AppError("backup_incomplete", status_code=500) from exc
        if not path.is_file() or stat.st_size != artifact.size_bytes or sha256_file(path) != artifact.sha256:
            raise AppError("backup_incomplete", status_code=500)
    try:
        actual = {
            path.relative_to(generation_dir).as_posix()
            for path in generation_dir.rglob("*")
            if path.is_file() and not is_link_or_reparse(path)
        }
        unsafe = any(
            is_link_or_reparse(path) or not (path.is_file() or path.is_dir()) for path in generation_dir.rglob("*")
        )
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if unsafe or actual != {MANIFEST_NAME, *expected}:
        raise AppError("backup_incomplete", status_code=500)


def _authority_payload(value: DatasetAuthority) -> dict[str, object]:
    return {
        "dataset_id": value.dataset_id,
        "client_generation": value.client_generation,
        "restore_epoch": value.restore_epoch,
        "schema_revision": value.schema_revision,
        "schema_min_compatible": value.schema_min_compatible,
        "semantic_revision": value.semantic_revision,
        "created_at_utc": _utc_text(value.created_at),
        "restored_from_backup_id": value.restored_from_backup_id,
    }


def _original_payload(value: OriginalArtifact) -> dict[str, object]:
    return {
        "storage_key": value.storage_key,
        "size_bytes": value.size_bytes,
        "sha256": value.sha256,
        "tenant_ids": list(value.tenant_ids),
    }


def _mapping(value: object, fields: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AppError("backup_incomplete", status_code=500)
    return value


def _uuid(value: object) -> str:
    try:
        result = str(UUID(str(value)))
    except (ValueError, TypeError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if result != value:
        raise AppError("backup_incomplete", status_code=500)
    return result


def _sha(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AppError("backup_incomplete", status_code=500)
    return value


def _plain_text(value: object, *, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(char in value for char in "\x00\r\n"):
        raise AppError("backup_incomplete", status_code=500)
    return value


def _datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AppError("backup_incomplete", status_code=500)
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if parsed.tzinfo is None or _utc_text(parsed) != value:
        raise AppError("backup_incomplete", status_code=500)
    return parsed


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise AppError("backup_incomplete", status_code=500)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AppError("backup_incomplete", status_code=500)
    return value


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AppError("backup_incomplete", status_code=500)
    return value


def _storage_key(value: object) -> str:
    text = _plain_text(value, limit=700).replace("\\", "/")
    parts = Path(text).parts
    if text.startswith("/") or len(parts) < 2 or parts[0] != ORIGINALS_DIRECTORY_NAME or ".." in parts:
        raise AppError("backup_incomplete", status_code=500)
    return "/".join(parts)
