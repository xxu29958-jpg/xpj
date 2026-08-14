"""Closed, read-only observation of one public ``app_meta`` value."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def read_app_meta_value(connection: Any, key: str) -> object:
    """Return one engine fact without importing the runtime database package."""

    return connection.scalar(
        text("SELECT value FROM public.app_meta WHERE key = :key"),
        {"key": key},
    )


__all__ = ["read_app_meta_value"]
