"""Actual funds and credit sources. Balances are projections of movements, never cached facts."""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.money_contract import money_check_constraints_for_table
from app.services.time_service import now_utc


class FinancialAccount(Base):
    __tablename__ = "financial_accounts"
    __table_args__ = (
        *money_check_constraints_for_table("financial_accounts"),
        CheckConstraint("kind IN ('cash','bank','wallet','credit')", name="ck_financial_accounts_kind"),
        CheckConstraint("visibility IN ('private','ledger')", name="ck_financial_accounts_visibility"),
        CheckConstraint("row_version > 0", name="ck_financial_accounts_version"),
        CheckConstraint("tail IS NULL OR length(tail) BETWEEN 1 AND 4", name="ck_financial_accounts_tail"),
        CheckConstraint("statement_day IS NULL OR statement_day BETWEEN 1 AND 31", name="ck_financial_accounts_statement_day"),
        CheckConstraint("payment_due_day IS NULL OR payment_due_day BETWEEN 1 AND 31", name="ck_financial_accounts_due_day"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid4()), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    owner_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    visibility: Mapped[str] = mapped_column(String(12), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(120))
    tail: Mapped[str | None] = mapped_column(String(4))
    credit_limit_minor: Mapped[int | None] = mapped_column(BigInteger)
    available_credit_minor: Mapped[int | None] = mapped_column(BigInteger)
    credit_observed_on: Mapped[date | None] = mapped_column(Date)
    credit_source: Mapped[str | None] = mapped_column(String(255))
    statement_day: Mapped[int | None] = mapped_column(Integer)
    payment_due_day: Mapped[int | None] = mapped_column(Integer)
    balance_known: Mapped[bool] = mapped_column(Boolean, nullable=False)
    opening_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_source: Mapped[str] = mapped_column(String(255), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CreditFacility(Base):
    __tablename__ = "credit_facilities"
    __table_args__ = (CheckConstraint("(adopted_at IS NULL) = (adopted_from IS NULL)", name="ck_credit_facility_adoption"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), unique=True, nullable=False)
    debt_id: Mapped[int] = mapped_column(Integer, ForeignKey("debts.id"), unique=True, nullable=False)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adopted_from: Mapped[dict | None] = mapped_column(JSON)


class ExpenseFunding(Base):
    __tablename__ = "expense_funding"
    __table_args__ = (*money_check_constraints_for_table("expense_funding"),
        UniqueConstraint("expense_id", "expense_row_version", "component_id", name="uq_expense_funding_component"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False)
    component_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Each side retains its own currency; a foreign account debit is not inferred from the purchase amount.
    expense_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    included_in_opening: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class AccountMovement(Base):
    __tablename__ = "account_movements"
    __table_args__ = (*money_check_constraints_for_table("account_movements"),
        UniqueConstraint("event_public_id", "component_id", name="uq_account_movement_event_component"),
        UniqueConstraint("funding_id", name="uq_account_movement_funding"),
        UniqueConstraint("reversal_of_id", name="uq_account_movement_reversal"),
        CheckConstraint("kind IN ('opening','expense','credit_draw','repayment','income','loan','transfer','refund','reconciliation','reversal')", name="ck_account_movement_kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid4()), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False, index=True)
    event_public_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    component_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    home_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    valuation_snapshot: Mapped[dict | None] = mapped_column(JSON)
    settlement_targets: Mapped[dict | None] = mapped_column(JSON)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    funding_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("expense_funding.id"))
    repayment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("repayments.id"), index=True)
    offset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("expense_offset_facts.id"))
    debt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("debts.id"))
    reversal_of_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account_movements.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CreditSettlementAllocation(Base):
    __tablename__ = "credit_settlement_allocations"
    __table_args__ = (*money_check_constraints_for_table("credit_settlement_allocations"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repayment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("repayments.id"))
    review_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("credit_application_reviews.id"))
    credit_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey("account_movements.id"), nullable=False)
    draw_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey("account_movements.id"), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    home_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    invalidated_by_movement_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account_movements.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class AccountBalanceObservation(Base):
    """An external statement and its explicit adjustment, never a replacement balance."""
    __tablename__ = "account_balance_observations"
    __table_args__ = (*money_check_constraints_for_table("account_balance_observations"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False, index=True)
    observed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    adjustment_movement_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account_movements.id"), unique=True)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
