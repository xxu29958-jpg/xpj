from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
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


class SchedulerLease(Base):
    """One coordination lease row per named in-process scheduler.

    Each FastAPI worker runs its own daemon scheduler threads; the scheduled
    jobs are idempotent, but multi-worker / cloud deployments should still avoid
    duplicate work without a queue broker. ``try_claim_scheduler_lease`` claims a
    lease atomically with a single ``INSERT ... ON CONFLICT (name) DO UPDATE ...
    WHERE expires_at <= now() RETURNING name`` (a returned row == claimed).

    ``expires_at`` is a real ``timestamptz`` so the claim compares times by type,
    not by the UTC-ISO ASCII lexicographic coincidence the prior ``app_meta``
    string value relied on. This is a process-coordination table only — it carries
    no business data and is never tenant-scoped.
    """

    __tablename__ = "scheduler_leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BootstrapSecretConsumption(Base):
    """Persistent record for one-time HTTP bootstrap secrets.

    The configured secret itself is never stored; only its SHA-256 hash is
    kept so process restarts preserve the one bootstrap transaction. The exact
    high-entropy secret may recover that transaction's deterministic
    credentials; it can never create a second identity set.
    """

    __tablename__ = "bootstrap_secret_consumptions"

    secret_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class InstallationOwnerClaim(Base):
    """One recoverable Windows installation-owner transaction.

    The operation ID remains stable across retries and bootstrap-secret
    rotation.  This machine-owned receipt intentionally carries no long-lived
    user credential.
    """

    __tablename__ = "installation_owner_claims"
    __table_args__ = (
        PrimaryKeyConstraint(
            "operation_id",
            name="pk_installation_owner_claims",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_installation_owner_claim_request_fingerprint",
        ),
        CheckConstraint(
            "active_secret_hash ~ '^[0-9a-f]{64}$'",
            name="ck_installation_owner_claim_secret_hash",
        ),
        CheckConstraint(
            "generation >= 1",
            name="ck_installation_owner_claim_generation",
        ),
        CheckConstraint(
            "pairing_derivation_index BETWEEN 0 AND 63",
            name="ck_installation_owner_claim_pairing_index",
        ),
        UniqueConstraint(
            "installation_id",
            name="uq_installation_owner_claim_installation_id",
        ),
        UniqueConstraint(
            "active_secret_hash",
            name="uq_installation_owner_claim_active_secret_hash",
        ),
        UniqueConstraint(
            "pairing_code_id",
            name="uq_installation_owner_claim_pairing_code_id",
        ),
    )

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    active_secret_hash: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "bootstrap_secret_consumptions.secret_hash",
            name="fk_installation_owner_claim_secret",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "accounts.id",
            name="fk_installation_owner_claim_account",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "devices.id",
            name="fk_installation_owner_claim_device",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    ledger_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "ledgers.ledger_id",
            name="fk_installation_owner_claim_ledger",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    pairing_code_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "pairing_codes.id",
            name="fk_installation_owner_claim_pairing",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    pairing_derivation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


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
