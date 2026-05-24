"""ADR-0036 AI alias mapping tables.

Three internal maps that keep the real PII local while the outbound AI
payload only sees opaque placeholders. These rows never leave the SQLite
file; they are read to translate the AI's response back ("``merchant_001``
in your AI answer means 麦当劳") before showing it to the user.

- ``AiMerchantAnonMap``: real merchant canonical name → ``merchant_NNN``.
- ``AiMemberAnonMap``: real account id → ``member_N``.
- ``AiTransactionTempIdMap``: per-AI-session expense id → ``tx_NNN``
  (scoped to a single advisor call so temp ids can be reused / pruned).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class AiMerchantAnonMap(Base):
    """Tenant-scoped merchant alias used only when serialising payloads to
    the AI advisor. ``merchant_canonical`` is the canonical form already
    produced by :class:`MerchantAlias` upstream (so synonyms collapse to
    one opaque id)."""

    __tablename__ = "ai_merchant_anon_map"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "merchant_canonical",
            name="uq_ai_merchant_anon_canonical",
        ),
        UniqueConstraint(
            "tenant_id",
            "anon_id",
            name="uq_ai_merchant_anon_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_ai_merchant_anon_tenant"),
        nullable=False,
        index=True,
    )
    merchant_canonical: Mapped[str] = mapped_column(String(255), nullable=False)
    anon_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class AiMemberAnonMap(Base):
    """Tenant-scoped family member alias used only when serialising
    payloads to the AI advisor. Real ``account_id`` stays local; outbound
    payloads use opaque ``member_N``."""

    __tablename__ = "ai_member_anon_map"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "account_id",
            name="uq_ai_member_anon_account",
        ),
        UniqueConstraint(
            "tenant_id",
            "anon_id",
            name="uq_ai_member_anon_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_ai_member_anon_tenant"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", name="fk_ai_member_anon_account"),
        nullable=False,
    )
    anon_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class BudgetAdvisorAuditLog(Base):
    """v1.1 Batch 2: persistent audit row per AI budget advisor call.

    Records who called, which provider/model handled it, success vs.
    failure, an input-payload hash (so identical-input replays can be
    grouped without storing the payload itself), and how many
    suggestions came back. Used by the Owner Console "AI 状态" panel to
    show recent activity without re-running the call.
    """

    __tablename__ = "budget_advisor_audit_logs"
    __table_args__ = (
        Index(
            "ix_budget_advisor_audit_tenant_called_at",
            "tenant_id",
            "called_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "ledgers.ledger_id", name="fk_budget_advisor_audit_tenant"
        ),
        nullable=False,
        index=True,
    )
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("accounts.id", name="fk_budget_advisor_audit_actor"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggestion_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class AiTransactionTempIdMap(Base):
    """Per-AI-call transaction placeholder. ``session_id`` lets one advisor
    call refer to a specific subset of expenses without leaking the real
    primary keys; rows can be pruned after the session ends without
    touching anything user-visible."""

    __tablename__ = "ai_transaction_temp_id_map"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "expense_id",
            name="uq_ai_tx_temp_session_expense",
        ),
        UniqueConstraint(
            "tenant_id",
            "session_id",
            "temp_id",
            name="uq_ai_tx_temp_session_id",
        ),
        Index("ix_ai_tx_temp_session", "tenant_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_ai_tx_temp_tenant"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    temp_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
