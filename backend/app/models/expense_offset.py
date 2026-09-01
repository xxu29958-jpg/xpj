"""Refund, chargeback, and reversal facts for a confirmed Expense."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.money_contract_types import MONEY_MINOR_MAX
from app.services.time_service import now_utc


class ExpenseOffsetFact(Base):
    """Current projection of one refund, chargeback, or reversal."""

    __tablename__ = "expense_offset_facts"
    __table_args__ = (
        CheckConstraint(
            f"amount_cents BETWEEN 1 AND {MONEY_MINOR_MAX}",
            name="ck_expense_offset_facts_amount_cents_money_bounds",
        ),
        CheckConstraint(
            f"original_amount_minor BETWEEN 1 AND {MONEY_MINOR_MAX}",
            name="ck_expense_offset_facts_original_amount_minor_money_bounds",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_offset_facts_expense_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_expense_offset_facts_id_tenant",
        ),
        CheckConstraint(
            "kind IN ('refund', 'chargeback', 'reversal')",
            name="ck_expense_offset_facts_kind_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'voided')",
            name="ck_expense_offset_facts_status_valid",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_offset_facts_reason_length",
        ),
        CheckConstraint(
            "row_version >= 1",
            name="ck_expense_offset_facts_row_version_positive",
        ),
        CheckConstraint(
            "fact_revision >= 1",
            name="ck_expense_offset_facts_fact_revision_positive",
        ),
        CheckConstraint(
            "(created_device_public_id IS NULL) = (created_device_name IS NULL)",
            name="ck_expense_offset_facts_device_snapshot_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active", nullable=False)
    original_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    original_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    home_currency_code: Mapped[str] = mapped_column(
        String(3),
        default=DEFAULT_HOME_CURRENCY_CODE,
        server_default=DEFAULT_HOME_CURRENCY_CODE,
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exchange_rate_to_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    accounting_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    fact_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_actor_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "accounts.id",
            name="fk_expense_offset_facts_created_actor",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_device_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_expense_offset_facts_tenant_expense_accounting",
    ExpenseOffsetFact.tenant_id,
    ExpenseOffsetFact.expense_id,
    ExpenseOffsetFact.accounting_date,
    ExpenseOffsetFact.id,
)
Index(
    "uq_expense_offset_facts_active_reversal",
    ExpenseOffsetFact.tenant_id,
    ExpenseOffsetFact.expense_id,
    unique=True,
    postgresql_where=((ExpenseOffsetFact.kind == "reversal") & (ExpenseOffsetFact.status == "active")),
)


class ExpenseOffsetRevision(Base):
    """Append-only evidence for an offset fact's complete lifecycle."""

    __tablename__ = "expense_offset_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["offset_id", "tenant_id"],
            ["expense_offset_facts.id", "expense_offset_facts.tenant_id"],
            name="fk_expense_offset_revisions_offset_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_offset_revisions_expense_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "offset_id",
            "revision_number",
            name="uq_expense_offset_revisions_offset_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_expense_offset_revisions_idempotency_key",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_expense_offset_revisions_number_positive",
        ),
        CheckConstraint(
            "change_kind IN ('created', 'correction', 'void')",
            name="ck_expense_offset_revisions_kind_valid",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_offset_revisions_reason_length",
        ),
        CheckConstraint(
            "(change_kind = 'created' AND before_snapshot IS NULL) OR "
            "(change_kind IN ('correction', 'void') AND before_snapshot IS NOT NULL)",
            name="ck_expense_offset_revisions_before_shape",
        ),
        CheckConstraint(
            "resulting_row_version >= 1",
            name="ck_expense_offset_revisions_result_version_positive",
        ),
        CheckConstraint(
            "(actor_device_public_id IS NULL) = (actor_device_name IS NULL)",
            name="ck_expense_offset_revisions_device_snapshot_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "accounts.id",
            name="fk_expense_offset_revisions_actor",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    actor_device_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    before_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    previous_row_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resulting_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index(
    "ix_expense_offset_revisions_tenant_expense_created",
    ExpenseOffsetRevision.tenant_id,
    ExpenseOffsetRevision.expense_id,
    ExpenseOffsetRevision.created_at,
)

event.listen(
    ExpenseOffsetRevision.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION ticketbox_reject_expense_offset_revision_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'expense_offset_revisions is append-only' USING ERRCODE = '55000'; "
        "END $$"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    ExpenseOffsetRevision.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_expense_offset_revisions_append_only "
        "BEFORE UPDATE OR DELETE ON expense_offset_revisions FOR EACH ROW "
        "EXECUTE FUNCTION ticketbox_reject_expense_offset_revision_mutation()"
    ).execute_if(dialect="postgresql"),
)
