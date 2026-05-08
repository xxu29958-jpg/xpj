from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="其他", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default="", nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="iPhone截图", nullable=False)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, default="", nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_draft_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_status: Mapped[str] = mapped_column(String(32), default="none", nullable=False, index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    duplicate_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regret_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    expense_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_expenses_tenant_status_created_at", Expense.tenant_id, Expense.status, Expense.created_at)
Index("ix_expenses_tenant_category_status", Expense.tenant_id, Expense.category, Expense.status)
Index("ix_expenses_tenant_status_expense_time", Expense.tenant_id, Expense.status, Expense.expense_time)
Index("ix_expenses_tenant_status_confirmed_at", Expense.tenant_id, Expense.status, Expense.confirmed_at)
Index("ix_expenses_tenant_status_category_expense_time", Expense.tenant_id, Expense.status, Expense.category, Expense.expense_time)
Index("ix_expenses_tenant_status_category_confirmed_at", Expense.tenant_id, Expense.status, Expense.category, Expense.confirmed_at)
Index("ix_expenses_tenant_status_amount_merchant", Expense.tenant_id, Expense.status, Expense.amount_cents, Expense.merchant)
Index("ix_expenses_tenant_image_hash", Expense.tenant_id, Expense.image_hash)
Index("ix_expenses_tenant_duplicate_status", Expense.tenant_id, Expense.duplicate_status)
Index("ix_expenses_status_created_at", Expense.status, Expense.created_at)
Index("ix_expenses_category_status", Expense.category, Expense.status)
Index("ix_expenses_status_expense_time", Expense.status, Expense.expense_time)
Index("ix_expenses_status_confirmed_at", Expense.status, Expense.confirmed_at)
Index("ix_expenses_status_category_expense_time", Expense.status, Expense.category, Expense.expense_time)
Index("ix_expenses_status_category_confirmed_at", Expense.status, Expense.category, Expense.confirmed_at)
Index("ix_expenses_status_amount_merchant", Expense.status, Expense.amount_cents, Expense.merchant)


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DuplicateIgnore(Base):
    __tablename__ = "duplicate_ignores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_id", "duplicate_of_id", "kind", name="uq_duplicate_ignore_tenant_pair_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    duplicate_of_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_category_rules_tenant_priority_id", CategoryRule.tenant_id, CategoryRule.priority, CategoryRule.id)
Index("ix_duplicate_ignores_tenant_pair_kind", DuplicateIgnore.tenant_id, DuplicateIgnore.expense_id, DuplicateIgnore.duplicate_of_id, DuplicateIgnore.kind)
