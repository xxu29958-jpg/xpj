from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from app.tenants import DEFAULT_TENANT_ID


class RecurringItem(Base):
    __tablename__ = "recurring_items"
    __table_args__ = (
        CheckConstraint("frequency IN ('monthly')", name="ck_recurring_items_frequency_valid"),
        CheckConstraint("status IN ('active', 'paused', 'archived')", name="ck_recurring_items_status_valid"),
        UniqueConstraint("tenant_id", "merchant_key", "frequency", name="uq_recurring_items_tenant_merchant_frequency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_recurring_items_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    merchant_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), default="monthly", nullable=False, index=True)
    baseline_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    last_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    next_expected_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="candidate", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_recurring_items_tenant_status_next", RecurringItem.tenant_id, RecurringItem.status, RecurringItem.next_expected_date)
Index("ix_recurring_items_tenant_merchant", RecurringItem.tenant_id, RecurringItem.merchant_key)
