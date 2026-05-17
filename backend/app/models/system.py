from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class SchemaMigration(Base):
    """Tracks which named migration steps have been applied to the SQLite DB.

    The legacy hand-written ``migrate_sqlite_schema`` in
    :mod:`app.database` is idempotent (uses ``ADD COLUMN`` /
    ``CREATE INDEX IF NOT EXISTS``), so this table is **purely informational**
    today — it does not gate execution. It exists so that future incremental
    migration scripts can record a stable identifier (e.g. ``"v0.9-add-foo"``)
    and be skipped on subsequent boots. See ``docs/roadmap/V2_ROADMAP.md`` and the
    audit notes in ``docs/architecture/VERSION.md``.
    """

    __tablename__ = "schema_migrations"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    backend_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

class UserUiPreference(Base):
    """v0.10: account-scoped UI preferences (theme, dashboard-card order key, ...).

    Cross-surface sync target: same account_name across web/Android shares the same row.
    `preferences` is a JSON-encoded text column to keep schema flexible (no migration on add).
    Currently used keys: `theme` (paper|mono|midnight). See docs/V0_9_DESIGN_TOKEN_REFERENCE.md.
    Owner Console is NOT a participant (single-device loopback role).
    """

    __tablename__ = "user_ui_preferences"

    account_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    preferences: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )
