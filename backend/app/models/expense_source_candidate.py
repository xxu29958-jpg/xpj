"""Independent transaction candidates from one retained extraction source."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class ExpenseSourceCandidate(Base):
    __tablename__ = "expense_source_candidates"
    __table_args__ = (
        ForeignKeyConstraint(["source_expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_source_candidate_source", ondelete="RESTRICT"),
        ForeignKeyConstraint(["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_source_candidate_target", ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "source_expense_id", "event_key", name="uq_expense_source_candidate_event"),
        UniqueConstraint("tenant_id", "expense_id", name="uq_expense_source_candidate_target"),
        CheckConstraint("event_index >= 0", name="ck_expense_source_candidate_index"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
