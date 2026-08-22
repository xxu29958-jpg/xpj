"""Sanitized runtime inventory and bounded retention for complete backups."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from app.config import DATA_ROOT
from app.errors import AppError
from app.services.dataset_backup_contract import BACKUP_KINDS, DatasetBackupManifest, read_manifest
from app.services.durable_publication import replace_durable_file
from app.services.path_entry_safety import is_link_or_reparse
from app.services.time_service import now_utc

INVENTORY_SCHEMA = "ticketbox-complete-backup-inventory-v1"
RETAINED_COMPLETE_GENERATIONS = 3
_GENERATION_PREFIX = "ticketbox-backup-"
_RETIRED_GENERATION_PREFIX = ".ticketbox-retired-backup-"
_INVENTORY_PATH = DATA_ROOT / "backup-inventory.json"
_BACKUP_DIRECTORY_LABEL = (
    f"{DATA_ROOT.parent.name}\\backups"
    if os.environ.get("TICKETBOX_DATA_ROOT_MARKER_PATH", "").strip()
    else f"{DATA_ROOT.name}\\backups"
)


@dataclass(frozen=True)
class BackupEntry:
    file_name: str
    backup_id: str
    dataset_id: str
    restore_epoch: int
    size_bytes: int
    created_at: datetime
    kind: str


@dataclass(frozen=True)
class PublishedBackupInventory:
    latest: BackupEntry | None
    age_hours: int | None
    review_due: bool
    integrity_status: Literal["absent", "not_rechecked"]


@dataclass(frozen=True)
class _VerifiedGeneration:
    path: Path
    entry: BackupEntry


def reconcile_published_backup_inventory(
    *,
    backup_root: Path,
    inventory_path: Path,
    required_generation: str,
) -> tuple[BackupEntry, ...]:
    """Verify the new generation, retain three, then atomically project metadata."""

    root = _plain_absolute_directory(backup_root)
    projection = _plain_absolute_file_target(inventory_path)
    required_id = _generation_backup_id(required_generation)
    verified = _verified_generations(root, required_generation=required_generation)
    required = next(
        (item for item in verified if item.entry.backup_id == required_id),
        None,
    )
    if required is None or required.entry.file_name != required_generation:
        raise AppError("backup_incomplete", status_code=409)

    newest = sorted(
        (item for item in verified if item is not required),
        key=lambda item: (item.entry.created_at, item.entry.backup_id),
        reverse=True,
    )
    retained = [required, *newest[: RETAINED_COMPLETE_GENERATIONS - 1]]
    retained_ids = {item.entry.backup_id for item in retained}
    entries = tuple(
        sorted(
            (item.entry for item in retained),
            key=lambda item: (item.created_at, item.backup_id),
            reverse=True,
        )
    )
    _write_inventory(projection, entries)
    for obsolete in verified:
        if obsolete.entry.backup_id not in retained_ids:
            _remove_verified_generation(root, obsolete)
    return entries


def list_published_backup_records(*, inventory_path: Path | None = None) -> list[BackupEntry]:
    """Read only the sanitized projection; never traverse backup payloads."""

    path = Path(os.path.abspath(inventory_path or _INVENTORY_PATH))
    if not path.exists():
        return []
    if not path.is_file() or is_link_or_reparse(path):
        raise AppError("backup_incomplete", status_code=500)
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "generations"}:
        raise AppError("backup_incomplete", status_code=500)
    generations = payload.get("generations")
    if payload.get("schema") != INVENTORY_SCHEMA or not isinstance(generations, list):
        raise AppError("backup_incomplete", status_code=500)
    entries = [_decode_entry(item) for item in generations]
    if len(entries) > RETAINED_COMPLETE_GENERATIONS:
        raise AppError("backup_incomplete", status_code=500)
    expected = sorted(
        entries,
        key=lambda item: (item.created_at, item.backup_id),
        reverse=True,
    )
    if entries != expected or len({entry.backup_id for entry in entries}) != len(entries):
        raise AppError("backup_incomplete", status_code=500)
    return entries


def latest_published_backup_record() -> BackupEntry | None:
    entries = list_published_backup_records()
    return entries[0] if entries else None


def published_backup_inventory(*, review_after_hours: int = 48) -> PublishedBackupInventory:
    """Report publication age separately from unperformed payload revalidation."""

    entry = latest_published_backup_record()
    if entry is None:
        return PublishedBackupInventory(
            latest=None,
            age_hours=None,
            review_due=True,
            integrity_status="absent",
        )
    age_hours = int((now_utc() - entry.created_at).total_seconds() // 3600)
    return PublishedBackupInventory(
        latest=entry,
        age_hours=age_hours,
        review_due=age_hours >= review_after_hours,
        integrity_status="not_rechecked",
    )


def backup_directory_label() -> str:
    return _BACKUP_DIRECTORY_LABEL


def _verified_generations(
    root: Path,
    *,
    required_generation: str,
) -> list[_VerifiedGeneration]:
    generations: list[_VerifiedGeneration] = []
    try:
        children = tuple(root.iterdir())
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    for path in children:
        if not path.name.startswith(_RETIRED_GENERATION_PREFIX):
            continue
        backup_id = _canonical_uuid(path.name.removeprefix(_RETIRED_GENERATION_PREFIX))
        if (
            path.parent != root
            or path.name != f"{_RETIRED_GENERATION_PREFIX}{backup_id}"
            or not path.is_dir()
            or is_link_or_reparse(path)
        ):
            raise AppError("backup_incomplete", status_code=500)
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise AppError("backup_incomplete", status_code=500) from exc
        if path.exists():
            raise AppError("backup_incomplete", status_code=500)
    for path in children:
        if not path.name.startswith(_GENERATION_PREFIX):
            continue
        required = path.name == required_generation
        try:
            _generation_backup_id(path.name)
            if not path.is_dir() or is_link_or_reparse(path):
                raise AppError("backup_incomplete", status_code=409)
            manifest = read_manifest(path, verify_files=True)
            if path.name != f"{_GENERATION_PREFIX}{manifest.backup_id}":
                raise AppError("backup_incomplete", status_code=409)
        except AppError:
            if required:
                raise
            continue
        generations.append(_VerifiedGeneration(path=path, entry=_entry(path.name, manifest)))
    return generations


def _remove_verified_generation(root: Path, generation: _VerifiedGeneration) -> None:
    path = generation.path
    try:
        resolved_root = root.resolve(strict=True)
        lexical = Path(os.path.abspath(path))
        lexical.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if lexical.parent != resolved_root or lexical.name != generation.entry.file_name:
        raise AppError("backup_incomplete", status_code=500)
    current = read_manifest(lexical, verify_files=True)
    if current.backup_id != generation.entry.backup_id:
        raise AppError("backup_incomplete", status_code=409)
    tombstone = resolved_root / f"{_RETIRED_GENERATION_PREFIX}{current.backup_id}"
    if tombstone.exists():
        raise AppError("backup_incomplete", status_code=500)
    try:
        lexical.rename(tombstone)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if lexical.exists():
        raise AppError("backup_incomplete", status_code=500)
    try:
        shutil.rmtree(tombstone)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if tombstone.exists():
        raise AppError("backup_incomplete", status_code=500)


def _write_inventory(path: Path, entries: tuple[BackupEntry, ...]) -> None:
    payload = {
        "schema": INVENTORY_SCHEMA,
        "generations": [_encode_entry(entry) for entry in entries],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    staging = path.parent / f".{path.name}.{uuid4()}.staging"
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        with staging.open("xb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        replace_durable_file(staging, path)
    except BaseException as exc:  # noqa: BLE001 - preserve publication failure
        primary = exc
    finally:
        try:
            staging.unlink(missing_ok=True)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup failure
            if primary is None:
                primary = exc
            else:
                cleanup.append(exc)
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "backup inventory publication and cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary


def _encode_entry(entry: BackupEntry) -> dict[str, object]:
    return {
        "generation": entry.file_name,
        "backup_id": entry.backup_id,
        "dataset_id": entry.dataset_id,
        "restore_epoch": entry.restore_epoch,
        "size_bytes": entry.size_bytes,
        "created_at": entry.created_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "kind": entry.kind,
    }


def _decode_entry(value: object) -> BackupEntry:
    fields = {
        "generation",
        "backup_id",
        "dataset_id",
        "restore_epoch",
        "size_bytes",
        "created_at",
        "kind",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise AppError("backup_incomplete", status_code=500)
    backup_id = _canonical_uuid(value["backup_id"])
    dataset_id = _canonical_uuid(value["dataset_id"])
    generation = value["generation"]
    restore_epoch = value["restore_epoch"]
    size_bytes = value["size_bytes"]
    kind = value["kind"]
    if (
        generation != f"{_GENERATION_PREFIX}{backup_id}"
        or not isinstance(restore_epoch, int)
        or isinstance(restore_epoch, bool)
        or restore_epoch < 0
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 1
        or kind not in BACKUP_KINDS
    ):
        raise AppError("backup_incomplete", status_code=500)
    created_at = _timestamp(value["created_at"])
    return BackupEntry(
        file_name=generation,
        backup_id=backup_id,
        dataset_id=dataset_id,
        restore_epoch=restore_epoch,
        size_bytes=size_bytes,
        created_at=created_at,
        kind=kind,
    )


def _entry(file_name: str, manifest: DatasetBackupManifest) -> BackupEntry:
    return BackupEntry(
        file_name=file_name,
        backup_id=manifest.backup_id,
        dataset_id=manifest.authority.dataset_id,
        restore_epoch=manifest.authority.restore_epoch,
        size_bytes=manifest.total_size_bytes,
        created_at=manifest.created_at,
        kind=manifest.backup_kind,
    )


def _plain_absolute_directory(path: Path) -> Path:
    if not path.is_absolute() or is_link_or_reparse(path):
        raise AppError("backup_incomplete", status_code=500)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not resolved.is_dir():
        raise AppError("backup_incomplete", status_code=500)
    return resolved


def _plain_absolute_file_target(path: Path) -> Path:
    if not path.is_absolute() or not path.name or is_link_or_reparse(path.parent):
        raise AppError("backup_incomplete", status_code=500)
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    target = Path(os.path.abspath(path))
    if target.parent != parent or is_link_or_reparse(target):
        raise AppError("backup_incomplete", status_code=500)
    return target


def _generation_backup_id(generation: object) -> str:
    if not isinstance(generation, str) or not generation.startswith(_GENERATION_PREFIX):
        raise AppError("backup_incomplete", status_code=500)
    return _canonical_uuid(generation.removeprefix(_GENERATION_PREFIX))


def _canonical_uuid(value: object) -> str:
    try:
        canonical = str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if canonical != value:
        raise AppError("backup_incomplete", status_code=500)
    return canonical


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AppError("backup_incomplete", status_code=500)
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise AppError("backup_incomplete", status_code=500)
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        raise AppError("backup_incomplete", status_code=500)
    return parsed


__all__ = [
    "BackupEntry",
    "PublishedBackupInventory",
    "RETAINED_COMPLETE_GENERATIONS",
    "backup_directory_label",
    "latest_published_backup_record",
    "list_published_backup_records",
    "published_backup_inventory",
    "reconcile_published_backup_inventory",
]
