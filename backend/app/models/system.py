from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class SchemaMigration(Base):
    """Tracks which named migration steps have been applied.

    ``record_schema_migration`` (in :mod:`app.database._seed`) writes a stable
    identifier here so a one-time step can be skipped on subsequent boots.
    ADR-0043 uses it exactly that way: the one-time ``expense_tags`` mirror
    reconcile (``reconcile_expense_tag_mirror_once``) gates on a row here via a
    cross-dialect read so it runs once on both SQLite and Postgres. See
    ``docs/roadmap/V2_ROADMAP.md`` and the audit notes in
    ``docs/architecture/VERSION.md``.
    """

    __tablename__ = "schema_migrations"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    backend_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BootstrapSecretConsumption(Base):
    """Persistent record for one-time HTTP bootstrap secrets.

    The configured secret itself is never stored; only its SHA-256 hash is
    kept so process restarts cannot make an already-used bootstrap secret
    usable again.
    """

    __tablename__ = "bootstrap_secret_consumptions"

    secret_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class UserUiPreference(Base):
    """v0.10: account-scoped UI preferences (theme, dashboard-card order key, ...).

    Cross-surface sync target: the same account_id across web/Android shares the same row.
    `preferences` is a JSON-encoded text column to keep schema flexible (no migration on add).
    Currently used keys: `theme` (paper|mono|midnight). See docs/V0_9_DESIGN_TOKEN_REFERENCE.md.
    Owner Console is NOT a participant (single-device loopback role).
    """

    __tablename__ = "user_ui_preferences"
    __table_args__ = (
        UniqueConstraint("account_id", name="uq_user_ui_preferences_account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", name="fk_user_ui_preferences_account"),
        nullable=False,
    )
    account_name: Mapped[str] = mapped_column(String(128), nullable=False)
    preferences: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


Index("ix_user_ui_preferences_account_id", UserUiPreference.account_id)
