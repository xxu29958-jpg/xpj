"""Closed, read-only observation of one public ``app_meta`` value."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, column, select, table

_APP_META = table(
    "app_meta",
    column("key"),
    column("value"),
    schema="public",
)
MANAGED_UPGRADE_ATTESTATION_KEY = "managed_upgrade_attestation"


def read_app_meta_value(connection: Any, key: str) -> object:
    """Return one engine fact without importing the runtime database package."""

    return connection.scalar(
        select(_APP_META.c.value).where(_APP_META.c.key == bindparam("key")),
        {"key": key},
    )


__all__ = ["MANAGED_UPGRADE_ATTESTATION_KEY", "read_app_meta_value"]
