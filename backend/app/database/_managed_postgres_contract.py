"""Stable PostgreSQL identities shared by managed schema operations."""

from __future__ import annotations

DATABASE_NAME = "ticketbox"
MIGRATOR_ROLE = "ticketbox_migrator"
SCHEMA_OWNER_ROLE = "ticketbox_owner"
MIGRATION_LEASE_LABEL = "xiaopiaojia:schema"

__all__ = [
    "DATABASE_NAME",
    "MIGRATION_LEASE_LABEL",
    "MIGRATOR_ROLE",
    "SCHEMA_OWNER_ROLE",
]
