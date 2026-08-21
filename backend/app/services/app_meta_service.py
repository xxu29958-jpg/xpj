"""Non-authoritative app metadata plus the dataset compatibility gate."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AppMeta
from app.services.dataset_authority_service import read_dataset_authority
from app.services.time_service import now_utc
from app.version import BACKEND_VERSION

V09_DEFAULT_VERSION = "0.9"
_RETIRED_DATASET_KEYS = frozenset({"server_id", "data_generation", "schema_version", "schema_min_compatible"})
_VERSION_PATTERN = re.compile(
    r"^\s*[vV]?(?P<release>\d+(?:\.\d+)*)"
    r"(?:(?:[-.]?)(?P<label>preview|alpha|beta|pre|dev|rc|a|b)"
    r"(?:[.-]?(?P<number>\d+))?)?"
    r"(?:\+[0-9A-Za-z.-]+)?\s*$",
    re.IGNORECASE,
)
_PRERELEASE_RANK = {
    "dev": -1,
    "a": 0,
    "alpha": 0,
    "b": 1,
    "beta": 1,
    "pre": 2,
    "preview": 2,
    "rc": 2,
}


def get_value(db: Session, key: str) -> str | None:
    row = db.scalar(select(AppMeta).where(AppMeta.key == key))
    return None if row is None else row.value


def set_value(db: Session, key: str, value: str) -> None:
    if key in _RETIRED_DATASET_KEYS:
        raise AppError("dataset_authority_read_only", status_code=500)
    row = db.scalar(select(AppMeta).where(AppMeta.key == key))
    if row is None:
        row = AppMeta(key=key, value=value, updated_at=now_utc())
        db.add(row)
    else:
        row.value = value
        row.updated_at = now_utc()
    db.commit()


def schema_min_compatible(db: Session) -> str:
    return read_dataset_authority(db).schema_min_compatible


def _version_tuple(v: str) -> tuple[tuple[int, ...], int, int]:
    """Return a comparable release/prerelease key for project version strings."""

    match = _VERSION_PATTERN.fullmatch(v)
    if match is None:
        raise ValueError(f"invalid project version: {v!r}")
    release = [int(piece) for piece in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    label = match.group("label")
    if label is None:
        return tuple(release), 3, 0
    number = int(match.group("number") or 0)
    return tuple(release), _PRERELEASE_RANK[label.lower()], number


def assert_binary_compatible_with_minimum(minimum: str | None) -> None:
    """Refuse a binary older than an available schema compatibility floor."""

    min_compat = minimum or V09_DEFAULT_VERSION
    my_version = BACKEND_VERSION
    try:
        is_too_old = _version_tuple(my_version) < _version_tuple(min_compat)
    except ValueError as exc:
        raise AppError(
            "invalid_schema_version",
            f"Invalid binary/schema version metadata: {exc}",
            status_code=500,
        ) from exc
    if is_too_old:
        raise AppError(
            "backend_version_too_old",
            (
                f"Backend binary {my_version!r} is older than the DB's "
                f"schema_min_compatible {min_compat!r}; refusing to start. "
                "Either upgrade the binary or restore the pre-cut-over backup."
            ),
            status_code=500,
        )


def assert_binary_compatible_with_db(db: Session) -> None:
    """Lifespan startup gate.

    Refuse to start when this binary's version is older than the DB's
    ``schema_min_compatible``. A newer binary is admitted only after the
    offline Generation Owner has published a schema generation it can run.

    Versions are compared by structured release and prerelease components.
    """
    assert_binary_compatible_with_minimum(schema_min_compatible(db))
