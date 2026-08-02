"""Database-bound reads of C07 installation metadata."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def read_app_meta_value(connection: Any, key: str) -> object:
    """Return one metadata value without leaking SQL into domain modules."""

    return connection.scalar(
        text("SELECT value FROM app_meta WHERE key = :key"),
        {"key": key},
    )


__all__ = ["read_app_meta_value"]
