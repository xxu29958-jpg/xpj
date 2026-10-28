"""Private original evidence for an explicit external-debt creation task."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class DebtBillCapture(Base):
    __tablename__ = "debt_bill_captures"
    __table_args__ = (
        UniqueConstraint("tenant_id", "capture_key", name="uq_debt_bill_capture_key"),
        UniqueConstraint("adopted_debt_public_id", name="uq_debt_bill_capture_debt"),
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="ck_debt_bill_capture_status"),
        CheckConstraint("row_version > 0 AND image_size_bytes > 0", name="ck_debt_bill_capture_version_size"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    creation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_receipt: Mapped[dict] = mapped_column(JSONB, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    image_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    image_evidence: Mapped[dict | None] = mapped_column(JSONB)
    image_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachment_cleanup_request: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parse_attempt_key: Mapped[str | None] = mapped_column(String(64))
    parse_request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    parse_outcome: Mapped[dict | None] = mapped_column(JSONB)
    adopted_debt_public_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("debts.public_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
