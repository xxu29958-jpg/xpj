"""Read the single PostgreSQL-owned Ticketbox dataset authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.dataset_authority import DatasetAuthorityRecord

DATASET_SEMANTIC_REVISION = "ticketbox-dataset-semantics-v1"
_ALEMBIC_REVISION = re.compile(r"[0-9]{8}_[0-9]{4}\Z")


@dataclass(frozen=True)
class DatasetAuthority:
    dataset_id: str
    restore_epoch: int
    schema_revision: str
    schema_min_compatible: str
    semantic_revision: str
    created_at: datetime
    restored_from_backup_id: str | None


def _canonical_uuid(value: str | None, *, field: str) -> str:
    try:
        canonical = str(UUID(value or ""))
    except (ValueError, AttributeError) as exc:
        raise AppError(
            "dataset_authority_invalid",
            f"Persisted {field} is missing or invalid.",
            status_code=500,
        ) from exc
    if value != canonical:
        raise AppError(
            "dataset_authority_invalid",
            f"Persisted {field} is not canonical.",
            status_code=500,
        )
    return canonical


def read_dataset_authority(db: Session) -> DatasetAuthority:
    row = db.get(DatasetAuthorityRecord, 1)
    if (
        row is None
        or row.restore_epoch < 0
        or _ALEMBIC_REVISION.fullmatch(row.schema_revision) is None
        or not row.schema_min_compatible
        or row.semantic_revision != DATASET_SEMANTIC_REVISION
    ):
        raise AppError("dataset_authority_invalid", status_code=500)
    restored_from = (
        None
        if row.restored_from_backup_id is None
        else _canonical_uuid(row.restored_from_backup_id, field="restored_from_backup_id")
    )
    return DatasetAuthority(
        dataset_id=_canonical_uuid(row.dataset_id, field="dataset_id"),
        restore_epoch=row.restore_epoch,
        schema_revision=row.schema_revision,
        schema_min_compatible=row.schema_min_compatible,
        semantic_revision=row.semantic_revision,
        created_at=row.created_at,
        restored_from_backup_id=restored_from,
    )


__all__ = [
    "DATASET_SEMANTIC_REVISION",
    "DatasetAuthority",
    "read_dataset_authority",
]
