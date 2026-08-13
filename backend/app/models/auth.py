from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class UploadLink(Base):
    __tablename__ = "upload_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    default_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Per-link daily byte budget. NULL = follow server default.
    daily_byte_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-remote min interval seconds between requests. 0 = no throttle.
    per_remote_min_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class UploadLinkDailyUsage(Base):
    """Daily byte counter per upload link.

    Single row per (upload_link_id, ymd). Updated atomically inside the
    same transaction that accepts the upload, so any reject path leaves
    the counter untouched.
    """

    __tablename__ = "upload_link_daily_usage"
    __table_args__ = (UniqueConstraint("upload_link_id", "ymd", name="uq_upload_link_daily_usage_link_ymd"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_link_id: Mapped[int] = mapped_column(Integer, ForeignKey("upload_links.id"), nullable=False, index=True)
    ymd: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    bytes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class UploadLinkRemoteAttempt(Base):
    """Last-attempt timestamp per (upload_link_id, remote_key).

    Backs the per-remote min-interval throttle without holding any
    process-local state. ``remote_key`` is the same hash/string the
    pairing rate-limit code derives (peer or CF-Connecting-IP).
    """

    __tablename__ = "upload_link_remote_attempts"
    __table_args__ = (
        UniqueConstraint(
            "upload_link_id",
            "remote_key",
            name="uq_upload_link_remote_attempts_link_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_link_id: Mapped[int] = mapped_column(Integer, ForeignKey("upload_links.id"), nullable=False, index=True)
    remote_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class PairingAttemptFailure(Base):
    """DB-backed pairing-attempt failure log.

    Replaces the previous in-process ``_pairing_failures_by_remote`` dict
    so the throttle survives backend restarts and is correct when running
    behind multiple workers. Cleaner ad-hoc: every check prunes rows older
    than ``PAIRING_ATTEMPT_WINDOW``.
    """

    __tablename__ = "pairing_attempt_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    remote_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    created_by_device_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recovery_device_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    device_name_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DeviceEnrollmentAttempt(Base):
    """Recoverable authorization transaction for one device enrollment.

    Pairing an existing Account and accepting an invitation for a new Account
    share one response-loss contract: the client persists ``public_id`` and a
    high-entropy proof before sending the one-shot credential. Exactly one
    source FK identifies the enrollment command; a proven retry returns the
    originally committed Device/session instead of creating another identity.
    """

    __tablename__ = "device_enrollment_attempts"
    __table_args__ = (
        CheckConstraint(
            "(pairing_code_id IS NOT NULL) <> (invitation_id IS NOT NULL)",
            name="ck_device_enrollment_attempts_one_source",
        ),
        UniqueConstraint(
            "pairing_code_id",
            name="uq_device_enrollment_attempts_pairing_code_id",
        ),
        UniqueConstraint(
            "invitation_id",
            name="uq_device_enrollment_attempts_invitation_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    pairing_code_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("pairing_codes.id", ondelete="CASCADE"), nullable=True
    )
    invitation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("invitations.id", ondelete="CASCADE"), nullable=True
    )
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_soft_refresh_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DesktopActivationAttempt(Base):
    """Recoverable transaction activating one staged desktop credential.

    Desktop pairing (and, later, desktop ledger-switch prepare) first stages a
    short-lived ``scope='desktop_pending'`` token. Every ordinary auth surface
    rejects that scope, so the only way forward is the activate endpoint with
    the stable attempt proof. This receipt makes the response-loss replay
    return the same committed activation instead of minting a second
    credential, and records the lineage from the superseded predecessor token.
    """

    __tablename__ = "desktop_activation_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    token_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("auth_tokens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    previous_token_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("auth_tokens.id", ondelete="CASCADE"),
        nullable=True,
    )
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class SessionRefreshAttempt(Base):
    """Recoverable transaction linking one old app token to its replacement."""

    __tablename__ = "session_refresh_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    source_token_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("auth_tokens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    replacement_token_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("auth_tokens.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_soft_refresh_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Invitation(Base):
    """Family ledger invitation token.

    Owner mints a one-time token bound to a (ledger_id, role). Plain token
    is returned to owner once and never persisted; only ``token_hash``
    (sha256 of the plain token) is stored. ``role`` must be ``member`` or
    ``viewer`` — owner role is granted only via initial ledger creation or
    explicit owner transfer.
    """

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint("role IN ('member', 'viewer')", name="ck_invitations_role_invitable"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
