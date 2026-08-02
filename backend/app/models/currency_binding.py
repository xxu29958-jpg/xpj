"""Installation-global currency authority for the cross-ADR C02 slice."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc

_BINDING_SHAPE_CHECK = """
(
    state = 'ACTIVE'
    AND home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')
    AND (
        (home_currency_code IN ('JPY', 'KRW') AND minor_unit_exponent = 0)
        OR
        (home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'HKD') AND minor_unit_exponent = 2)
    )
    AND rounding_mode = 'ROUND_HALF_UP'
    AND binding_revision >= 1
    AND provenance IS NOT NULL
    AND evidence_sha256 ~ '^[0-9a-f]{64}$'
    AND activated_at IS NOT NULL
)
OR
(
    state IN ('EMPTY', 'ADOPTION_REQUIRED')
    AND home_currency_code IS NULL
    AND minor_unit_exponent IS NULL
    AND rounding_mode IS NULL
    AND binding_revision = 0
    AND provenance IS NULL
    AND evidence_sha256 IS NULL
    AND activated_at IS NULL
)
""".strip()


class InstallationCurrencyBinding(Base):
    """The one persisted interpretation for every installation money integer."""

    __tablename__ = "installation_currency_bindings"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_installation_currency_binding_singleton"),
        CheckConstraint(
            "state IN ('EMPTY', 'ADOPTION_REQUIRED', 'ACTIVE')",
            name="ck_installation_currency_binding_state",
        ),
        CheckConstraint(
            "currency_contract_version >= 1",
            name="ck_installation_currency_binding_contract_version",
        ),
        CheckConstraint(
            _BINDING_SHAPE_CHECK,
            name="ck_installation_currency_binding_shape",
        ),
    )

    singleton_id: Mapped[int] = mapped_column(
        SmallInteger,
        primary_key=True,
        default=1,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="EMPTY")
    home_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    minor_unit_exponent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rounding_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency_contract_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    binding_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provenance: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class InstallationIdempotencyKey(Base):
    """Installation-scoped replay record for non-ledger maintenance commands."""

    __tablename__ = "installation_idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'succeeded')",
            name="ck_installation_idempotency_status",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_installation_idempotency_uuid4",
        ),
        CheckConstraint(
            "(status = 'in_progress' AND receipt IS NULL AND completed_at IS NULL) "
            "OR (status = 'succeeded' AND receipt IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_installation_idempotency_completion_shape",
        ),
        Index("ix_installation_idempotency_expires_at", "expires_at"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    receipt: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InstallationCurrencyAuditLog(Base):
    """Append-only state-transition evidence without credential secrets."""

    __tablename__ = "installation_currency_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('FIRST_FACT_CLAIM', 'OWNER_ADOPTION')",
            name="ck_installation_currency_audit_action",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_installation_currency_audit_reason",
        ),
        CheckConstraint(
            "(actor_account_public_id IS NULL) = (actor_device_public_id IS NULL)",
            name="ck_installation_currency_audit_actor_shape",
        ),
    )

    event_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_account_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_device_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=now_utc,
    )
