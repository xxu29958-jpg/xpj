"""Stable logical server and restore-generation identity.

Both values live with PostgreSQL business data, so host/path migration does
not change the logical server. ``data_generation`` is rotated by a verified
restore/fork workflow before clients may resume queued writes; normal restarts
and upgrades preserve it.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AppMeta
from app.services.time_service import now_utc

SERVER_ID_META = "server_id"
DATA_GENERATION_META = "data_generation"


@dataclass(frozen=True)
class ServerDataIdentity:
    server_id: str
    data_generation: str


def _canonical_uuid(value: str | None, *, field: str) -> str:
    try:
        canonical = str(UUID(value or ""))
    except (ValueError, AttributeError) as exc:
        raise AppError(
            "server_identity_invalid",
            f"Persisted {field} is missing or invalid.",
            status_code=500,
        ) from exc
    if value != canonical:
        raise AppError(
            "server_identity_invalid",
            f"Persisted {field} is not canonical.",
            status_code=500,
        )
    return canonical


def read_server_data_identity(db: Session) -> ServerDataIdentity:
    values = dict(
        db.execute(
            select(AppMeta.key, AppMeta.value).where(
                AppMeta.key.in_((SERVER_ID_META, DATA_GENERATION_META))
            )
        ).all()
    )
    return ServerDataIdentity(
        server_id=_canonical_uuid(values.get(SERVER_ID_META), field=SERVER_ID_META),
        data_generation=_canonical_uuid(
            values.get(DATA_GENERATION_META),
            field=DATA_GENERATION_META,
        ),
    )


def rotate_data_generation_after_verified_restore(db: Session) -> ServerDataIdentity:
    """Advance the replay boundary after a restore has been verified."""

    row = db.get(AppMeta, DATA_GENERATION_META)
    if row is None:
        raise AppError("server_identity_invalid", status_code=500)
    row.value = str(uuid4())
    row.updated_at = now_utc()
    db.commit()
    return read_server_data_identity(db)
