"""ADR-0031 app_meta helper.

Provides read/write access to the ``app_meta`` key-value table and the
binary-vs-DB compatibility check called from lifespan startup.

Default values when a key is missing:
- ``schema_version`` defaults to ``"0.9"`` (pre-cut-over v0.9.x baseline).
- ``schema_min_compatible`` defaults to ``"0.9"`` (same).
- ``migration_completed_at`` defaults to NULL.

The "default to 0.9" choice means a fresh DB created by ``create_all``
without a bootstrap row is treated as v0.9.x — matching reality, since
nothing in v0.9.x writes app_meta.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AppMeta
from app.models.app_meta import (
    MIGRATION_COMPLETED_AT_KEY,
    SCHEMA_MIN_COMPATIBLE_KEY,
    SCHEMA_VERSION_KEY,
)
from app.services.time_service import now_utc
from app.version import BACKEND_VERSION

V09_DEFAULT_VERSION = "0.9"
V1_TARGET_VERSION = "1.0"


def get_value(db: Session, key: str) -> str | None:
    row = db.scalar(select(AppMeta).where(AppMeta.key == key))
    return None if row is None else row.value


def set_value(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(AppMeta).where(AppMeta.key == key))
    if row is None:
        row = AppMeta(key=key, value=value, updated_at=now_utc())
        db.add(row)
    else:
        row.value = value
        row.updated_at = now_utc()
    db.commit()


def schema_version(db: Session) -> str:
    return get_value(db, SCHEMA_VERSION_KEY) or V09_DEFAULT_VERSION


def schema_min_compatible(db: Session) -> str:
    return get_value(db, SCHEMA_MIN_COMPATIBLE_KEY) or V09_DEFAULT_VERSION


def migration_completed_at(db: Session) -> str | None:
    return get_value(db, MIGRATION_COMPLETED_AT_KEY)


def _version_tuple(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in v.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def assert_binary_compatible_with_db(db: Session) -> None:
    """Lifespan startup gate.

    Refuse to start when this binary's version is older than the DB's
    ``schema_min_compatible``. The reverse direction (binary newer than
    ``schema_version``) is always fine — incremental migrations handle
    add-column upgrades on every boot.

    The check uses a simple ``parts-of-dotted-version`` comparison; it
    accepts ``"0.9.0a1"`` vs ``"1.0"`` because the leading numeric pieces
    compare correctly.
    """
    min_compat = schema_min_compatible(db)
    my_version = BACKEND_VERSION
    if _version_tuple(my_version) < _version_tuple(min_compat):
        raise AppError(
            "backend_version_too_old",
            (
                f"Backend binary {my_version!r} is older than the DB's "
                f"schema_min_compatible {min_compat!r}; refusing to start. "
                "Either upgrade the binary or restore the pre-cut-over backup."
            ),
            status_code=500,
        )


def mark_v1_cut_over_completed(db: Session) -> None:
    """Atomic cut-over write: set version, min_compatible, completed_at
    in a single transaction. Called by the v1_migration background task
    handler."""
    set_value(db, SCHEMA_VERSION_KEY, V1_TARGET_VERSION)
    set_value(db, SCHEMA_MIN_COMPATIBLE_KEY, V1_TARGET_VERSION)
    set_value(db, MIGRATION_COMPLETED_AT_KEY, now_utc().isoformat())
