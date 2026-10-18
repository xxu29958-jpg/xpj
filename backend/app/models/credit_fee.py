"""Classify an incurred Expense as a credit fee, without duplicating its money."""
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base


class CreditFeeObligation(Base):
    __tablename__ = "credit_fee_obligations"
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False, index=True)
    period_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("installment_periods.id"))
