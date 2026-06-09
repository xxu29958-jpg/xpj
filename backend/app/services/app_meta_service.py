"""ADR-0031 app_meta helper.

Provides read/write access to the ``app_meta`` key-value table and the
binary-vs-DB compatibility check called from lifespan startup.

Default values when a key is missing at runtime:
- ``schema_version`` defaults to ``"0.9"`` (legacy pre-cut-over baseline).
- ``schema_min_compatible`` defaults to ``"0.9"`` (same).

Startup stamps brand-new empty databases with the current backend version.
The "default to 0.9" path is reserved for old databases that already contain
domain rows but were created before app_meta existed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AppMeta, Ledger
from app.models.app_meta import (
    SCHEMA_MIN_COMPATIBLE_KEY,
    SCHEMA_VERSION_KEY,
)
from app.services.time_service import now_utc
from app.version import BACKEND_VERSION

V09_DEFAULT_VERSION = "0.9"


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


def _set_value_in_transaction(
    db: Session, key: str, value: str, *, updated_at: datetime
) -> None:
    row = db.scalar(select(AppMeta).where(AppMeta.key == key))
    if row is None:
        row = AppMeta(key=key, value=value, updated_at=updated_at)
        db.add(row)
    else:
        row.value = value
        row.updated_at = updated_at


def schema_version(db: Session) -> str:
    return get_value(db, SCHEMA_VERSION_KEY) or V09_DEFAULT_VERSION


def schema_min_compatible(db: Session) -> str:
    return get_value(db, SCHEMA_MIN_COMPATIBLE_KEY) or V09_DEFAULT_VERSION


def seed_fresh_schema_metadata(db: Session) -> None:
    """Stamp brand-new databases so missing app_meta only means legacy DB."""

    if get_value(db, SCHEMA_VERSION_KEY) is not None:
        return
    ledger_count = int(db.scalar(select(func.count(Ledger.id))) or 0)
    if ledger_count > 0:
        return
    now = now_utc()
    for key in (SCHEMA_VERSION_KEY, SCHEMA_MIN_COMPATIBLE_KEY):
        _set_value_in_transaction(db, key, BACKEND_VERSION, updated_at=now)
    db.commit()


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
    ``schema_version``) is always fine; incremental migrations handle
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
