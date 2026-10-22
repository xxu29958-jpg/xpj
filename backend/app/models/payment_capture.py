"""One account-scoped notification identity, before any financial confirmation."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base


class PaymentCapture(Base):
    __tablename__ = "payment_captures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_account_id", "identity_hash", name="uq_payment_capture_identity"),
        UniqueConstraint("repayment_public_id", name="uq_payment_capture_repayment"),
        UniqueConstraint("expense_public_id", name="uq_payment_capture_expense"),
        CheckConstraint("kind IN ('review', 'expense', 'repayment', 'dismissed')", name="ck_payment_capture_kind"),
        CheckConstraint("row_version > 0", name="ck_payment_capture_version"),
        CheckConstraint("original_amount_minor IS NULL OR original_amount_minor > 0", name="ck_payment_capture_amount"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    # Historical drafts can be linked before the device supplies its retained identity.
    identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    original_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    time_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    expense_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    repayment_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decisions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
