"""Current release-head verification, independent of historical invariants."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError


class ReleaseHeadVerificationError(RuntimeError):
    """The live database does not expose the required single release head."""


def read_release_head(connection: Connection) -> str:
    try:
        revisions = tuple(
            str(value)
            for value in connection.scalars(text("SELECT version_num FROM public.alembic_version ORDER BY version_num"))
        )
    except SQLAlchemyError as exc:
        raise ReleaseHeadVerificationError("release head cannot be read") from exc
    if len(revisions) != 1:
        raise ReleaseHeadVerificationError("release database must expose exactly one Alembic head")
    return revisions[0]


def assert_release_head(
    connection: Connection,
    *,
    expected_revision: str,
) -> str:
    current = read_release_head(connection)
    if current != expected_revision:
        raise ReleaseHeadVerificationError("live database does not match the required release head")
    return current


__all__ = [
    "ReleaseHeadVerificationError",
    "assert_release_head",
    "read_release_head",
]
