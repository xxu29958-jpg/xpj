"""ADR-0029 cross-ledger bill split invitation.

State machine: ``invited`` -> ``accepted | rejected | cancelled | expired``.

Account-scoped inbox (NOT ledger-scoped): ``receiver_ledger_id`` /
``receiver_member_id`` are NULL in the ``invited`` state and only get
filled when the receiver accepts and chooses a target ledger they have
write permission on. This preserves [[ADR-0022]] personal-ledger privacy
in both directions: sender never knows which ledger receiver accepted to,
and receiver never sees sender's expense_id / ledger_id (those are kept
server-side but excluded from inbox DTOs).
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class BillSplitInvitation(Base):
    """Cross-ledger bill split invitation; see ADR-0029."""

    __tablename__ = "bill_split_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('invited', 'accepted', 'rejected', 'cancelled', 'expired')",
            name="ck_bill_split_invitations_status_valid",
        ),
        CheckConstraint(
            "amount_cents > 0",
            name="ck_bill_split_invitations_amount_positive",
        ),
        # When accepted: receiver_ledger_id, receiver_member_id, and
        # received_expense_id all present. When NOT accepted: all three
        # NULL. We don't enforce this via CHECK (SQLite gets cranky about
        # cross-column predicates) — service layer is the source of truth.
        ForeignKeyConstraint(
            ["sender_member_id", "sender_ledger_id"],
            ["ledger_members.id", "ledger_members.ledger_id"],
            name="fk_bill_split_invitations_sender_member_tenant",
        ),
        ForeignKeyConstraint(
            ["sender_expense_id", "sender_ledger_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_bill_split_invitations_sender_expense_tenant",
        ),
        # Receiver FK is composite + nullable; SQLite is lenient on
        # nullable composite FKs.
        ForeignKeyConstraint(
            ["receiver_member_id", "receiver_ledger_id"],
            ["ledger_members.id", "ledger_members.ledger_id"],
            name="fk_bill_split_invitations_receiver_member_tenant",
        ),
        ForeignKeyConstraint(
            ["received_expense_id", "receiver_ledger_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_bill_split_invitations_received_expense_tenant",
        ),
        UniqueConstraint("received_expense_id", name="uq_bill_split_received_expense_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )

    # --- sender (always populated) -----------------------------------
    sender_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    sender_ledger_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True
    )
    sender_member_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_expense_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sender_display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- receiver target account (always populated) ------------------
    receiver_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    receiver_display_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- receiver ledger choice (NULL until accept) ------------------
    receiver_ledger_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receiver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- money snapshot (frozen at create) ---------------------------
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    original_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    original_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_rate_to_cny = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- snapshot fields (NOT FK; deliberate copy not pierce) --------
    merchant_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category_suggestion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expense_time_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- state machine -----------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), default="invited", server_default="invited", nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_expense_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_bill_split_invitations_receiver_status_created",
    BillSplitInvitation.receiver_account_id,
    BillSplitInvitation.status,
    BillSplitInvitation.created_at,
)
Index(
    "ix_bill_split_invitations_sender_status_created",
    BillSplitInvitation.sender_account_id,
    BillSplitInvitation.sender_ledger_id,
    BillSplitInvitation.status,
    BillSplitInvitation.created_at,
)
Index(
    "ix_bill_split_invitations_expires_at_status",
    BillSplitInvitation.expires_at,
    BillSplitInvitation.status,
)
Index(
    "uq_bill_split_invitations_pending_receiver",
    BillSplitInvitation.sender_expense_id,
    BillSplitInvitation.receiver_account_id,
    unique=True,
    sqlite_where=BillSplitInvitation.status == "invited",
    postgresql_where=BillSplitInvitation.status == "invited",
)
