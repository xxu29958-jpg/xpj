"""An explicit use of retained credit; it never changes the account's money balance."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.money_contract import money_check_constraints_for_table
from app.services.time_service import now_utc


class CreditApplicationReview(Base):
    __tablename__ = "credit_application_reviews"
    __table_args__ = (*money_check_constraints_for_table("credit_application_reviews"),
        CheckConstraint("(voided_at IS NULL AND void_reason IS NULL AND void_actor_account_id IS NULL) OR "
            "(voided_at IS NOT NULL AND void_reason IS NOT NULL AND void_actor_account_id IS NOT NULL)",
            name="ck_credit_application_void"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid4()), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), nullable=False, index=True)
    credit_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey("account_movements.id"), nullable=False)
    draw_movement_id: Mapped[int] = mapped_column(Integer, ForeignKey("account_movements.id"), nullable=False)
    # This is the reviewed instruction; settlement allocations remain the only applied amount.
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(255))
    void_actor_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"))
