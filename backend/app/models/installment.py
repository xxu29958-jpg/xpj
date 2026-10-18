"""A versioned actual credit agreement; schedules do not publish money movements."""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.money_contract import money_check_constraints_for_table
from app.services.time_service import now_utc


class InstallmentAgreement(Base):
    __tablename__ = "installment_agreements"
    __table_args__ = (UniqueConstraint("series_id", "revision", name="uq_installment_revision"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False, index=True)
    series_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("installment_agreements.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(500), nullable=False)
    agreed_on: Mapped[date] = mapped_column(Date, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)


class InstallmentDraw(Base):
    __tablename__ = "installment_draws"
    __table_args__ = (*money_check_constraints_for_table("installment_draws"),
        UniqueConstraint("agreement_id", "movement_id", name="uq_installment_draw"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agreement_id: Mapped[int] = mapped_column(Integer, ForeignKey("installment_agreements.id"), nullable=False)
    movement_id: Mapped[int] = mapped_column(Integer, ForeignKey("account_movements.id"), nullable=False)
    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class InstallmentPeriod(Base):
    __tablename__ = "installment_periods"
    __table_args__ = (*money_check_constraints_for_table("installment_periods"),
        UniqueConstraint("agreement_id", "position", name="uq_installment_period_position"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    agreement_id: Mapped[int] = mapped_column(Integer, ForeignKey("installment_agreements.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    planned_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class InstallmentPayment(Base):
    __tablename__ = "installment_payments"
    __table_args__ = (*money_check_constraints_for_table("installment_payments"),
        CheckConstraint("principal_minor > 0 OR fee_minor > 0", name="ck_installment_payment_nonempty"),
        UniqueConstraint("period_id", "repayment_id", name="uq_installment_payment"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(Integer, ForeignKey("installment_periods.id"), nullable=False)
    repayment_id: Mapped[int] = mapped_column(Integer, ForeignKey("repayments.id"), nullable=False)
    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_expense_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("expenses.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
