"""Migrations for duplicate_ignores + upload_links — small auxiliary tables."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect, text

from app.tenants import DEFAULT_TENANT_ID


def _migrate_duplicate_ignores(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("duplicate_ignores")}
    if "tenant_id" not in columns:
        connection.execute(text(
            f"ALTER TABLE duplicate_ignores ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
        ))
    if "kind" not in columns:
        connection.execute(text("ALTER TABLE duplicate_ignores ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'manual'"))
    connection.execute(
        text("UPDATE duplicate_ignores SET tenant_id = :tenant_id WHERE tenant_id IS NULL OR tenant_id = ''"),
        {"tenant_id": DEFAULT_TENANT_ID},
    )
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_pair_kind "
        "ON duplicate_ignores (expense_id, duplicate_of_id, kind)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_duplicate_ignore_tenant_pair_kind "
        "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_duplicate_ignores_tenant_pair_kind "
        "ON duplicate_ignores (tenant_id, expense_id, duplicate_of_id, kind)"
    ))


def _migrate_upload_links(connection) -> None:
    """v0.3.1-alpha2: backfill upload_links.public_id for rows created
    before the column existed.

    v1.1 hardening: additive columns ``daily_byte_budget`` /
    ``per_remote_min_interval_seconds`` for per-link quota + throttle,
    and ``expires_at`` for hard UploadLink expiry.
    """
    columns = {column["name"] for column in inspect(connection).get_columns("upload_links")}
    if "public_id" not in columns:
        connection.execute(text("ALTER TABLE upload_links ADD COLUMN public_id VARCHAR(36)"))
    if "expires_at" not in columns:
        connection.execute(text("ALTER TABLE upload_links ADD COLUMN expires_at DATETIME"))
    if "daily_byte_budget" not in columns:
        connection.execute(text(
            "ALTER TABLE upload_links ADD COLUMN daily_byte_budget INTEGER"
        ))
    if "per_remote_min_interval_seconds" not in columns:
        connection.execute(text(
            "ALTER TABLE upload_links ADD COLUMN per_remote_min_interval_seconds "
            "INTEGER NOT NULL DEFAULT 0"
        ))
    empty_rows = connection.execute(
        text("SELECT id FROM upload_links WHERE public_id IS NULL OR public_id = ''")
    ).mappings()
    for row in empty_rows:
        connection.execute(
            text("UPDATE upload_links SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid4()), "id": row["id"]},
        )
    from app.config import get_settings

    ttl_days = max(get_settings().upload_link_ttl_days, 1)
    connection.execute(
        text(
            "UPDATE upload_links "
            "SET expires_at = datetime('now', '+' || :ttl_days || ' days') "
            "WHERE expires_at IS NULL"
        ),
        {"ttl_days": ttl_days},
    )
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_upload_links_public_id "
        "ON upload_links (public_id)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_upload_links_expires_at "
        "ON upload_links (expires_at)"
    ))
