"""Sanitized runtime inventory and bounded retention for complete backups."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.config import DATA_ROOT
from app.errors import AppError
from app.services.dataset_backup_contract import BACKUP_KINDS
from app.services.path_entry_safety import is_link_or_reparse
from app.services.time_service import now_utc

INVENTORY_SCHEMA = "ticketbox-complete-backup-inventory-v1"
RETAINED_COMPLETE_GENERATIONS = 3
_GENERATION_PREFIX = "ticketbox-backup-"
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
    age_status: Literal["absent", "observed", "future"]
    review_due: bool
    integrity_status: Literal["absent", "not_rechecked"]


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
            age_status="absent",
            review_due=True,
            integrity_status="absent",
        )
    age_seconds = (now_utc() - entry.created_at).total_seconds()
    if age_seconds < 0:
        return PublishedBackupInventory(
            latest=entry,
            age_hours=None,
            age_status="future",
            review_due=True,
            integrity_status="not_rechecked",
        )
    age_hours = int(age_seconds // 3600)
    return PublishedBackupInventory(
        latest=entry,
        age_hours=age_hours,
        age_status="observed",
        review_due=age_hours >= review_after_hours,
        integrity_status="not_rechecked",
    )


def backup_directory_label() -> str:
    return _BACKUP_DIRECTORY_LABEL


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
]
