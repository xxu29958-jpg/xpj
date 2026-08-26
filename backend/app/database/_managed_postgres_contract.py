"""Stable PostgreSQL identities shared by managed schema operations."""

from __future__ import annotations

DATABASE_NAME = "ticketbox"
BACKUP_ROLE = "ticketbox_backup"
MIGRATOR_ROLE = "ticketbox_migrator"
RUNTIME_ROLE = "ticketbox_runtime"
SCHEMA_OWNER_ROLE = "ticketbox_owner"
RUNTIME_READ_ONLY_TABLES = ("alembic_version", "dataset_authority")
MIGRATION_LEASE_LABEL = "xiaopiaojia:schema"

__all__ = [
    "BACKUP_ROLE",
    "DATABASE_NAME",
    "MIGRATION_LEASE_LABEL",
    "MIGRATOR_ROLE",
    "RUNTIME_ROLE",
    "RUNTIME_READ_ONLY_TABLES",
    "SCHEMA_OWNER_ROLE",
]
