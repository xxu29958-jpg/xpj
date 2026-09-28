"""Ledger-shared named queries over the confirmed financial stream."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class SavedView(Base):
    __tablename__ = "saved_views"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name_key", name="uq_saved_views_tenant_name_key"),
        CheckConstraint("month_mode IN ('fixed', 'current')", name="ck_saved_views_month_mode"),
        CheckConstraint("filter IN ('', 'missing_category', 'missing_accounting_date')", name="ck_saved_views_filter"),
        CheckConstraint("(month_mode = 'fixed' AND month IS NOT NULL) OR "
                        "(month_mode = 'current' AND month IS NULL)", name="ck_saved_views_month_binding"),
        CheckConstraint("row_version >= 1", name="ck_saved_views_row_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(120), nullable=False)
    month_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    filter: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    tag_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
