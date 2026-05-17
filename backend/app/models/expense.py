from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_expenses_id_tenant_id"),
        CheckConstraint(
            "amount_cents IS NULL OR amount_cents >= 0",
            name="ck_expenses_amount_non_negative",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="ck_expenses_status_valid",
        ),
        CheckConstraint(
            "duplicate_status IN ('none', 'suspected')",
            name="ck_expenses_duplicate_status_valid",
        ),
    )

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
    draft_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
Index("ix_expenses_tenant_status_merchant_expense_time", Expense.tenant_id, Expense.status, Expense.merchant, Expense.expense_time)
Index("ix_expenses_tenant_status_merchant_confirmed_at", Expense.tenant_id, Expense.status, Expense.merchant, Expense.confirmed_at)
Index("ix_expenses_tenant_draft_idempotency_key", Expense.tenant_id, Expense.draft_idempotency_key, unique=True)
Index("ix_expenses_tenant_image_hash", Expense.tenant_id, Expense.image_hash)
Index("ix_expenses_tenant_duplicate_status", Expense.tenant_id, Expense.duplicate_status)
Index("ix_expenses_status_created_at", Expense.status, Expense.created_at)
Index("ix_expenses_category_status", Expense.category, Expense.status)
Index("ix_expenses_status_expense_time", Expense.status, Expense.expense_time)
Index("ix_expenses_status_confirmed_at", Expense.status, Expense.confirmed_at)
Index("ix_expenses_status_category_expense_time", Expense.status, Expense.category, Expense.expense_time)
Index("ix_expenses_status_category_confirmed_at", Expense.status, Expense.category, Expense.confirmed_at)
Index("ix_expenses_status_amount_merchant", Expense.status, Expense.amount_cents, Expense.merchant)
Index("ix_expenses_status_merchant_expense_time", Expense.status, Expense.merchant, Expense.expense_time)
Index("ix_expenses_status_merchant_confirmed_at", Expense.status, Expense.merchant, Expense.confirmed_at)


class ExpenseItem(Base):
    __tablename__ = "expense_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_expense_items_position_non_negative"),
        CheckConstraint("amount_cents IS NULL OR amount_cents >= 0", name="ck_expense_items_amount_non_negative"),
        CheckConstraint(
            "unit_price_cents IS NULL OR unit_price_cents >= 0",
            name="ck_expense_items_unit_price_non_negative",
        ),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_expense_items_confidence"),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_items_expense_tenant",
        ),
        UniqueConstraint("tenant_id", "expense_id", "position", name="uq_expense_items_tenant_expense_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="其他", nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_ocr_draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_expense_items_tenant_expense_position", ExpenseItem.tenant_id, ExpenseItem.expense_id, ExpenseItem.position)
Index("ix_expense_items_tenant_public_id", ExpenseItem.tenant_id, ExpenseItem.public_id)
Index("ix_expense_items_tenant_category", ExpenseItem.tenant_id, ExpenseItem.category)


class ExpenseSplit(Base):
    __tablename__ = "expense_splits"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_expense_splits_position_non_negative"),
        CheckConstraint("amount_cents >= 0", name="ck_expense_splits_amount_non_negative"),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_splits_expense_tenant",
        ),
        ForeignKeyConstraint(
            ["member_id", "tenant_id"],
            ["ledger_members.id", "ledger_members.ledger_id"],
            name="fk_expense_splits_member_tenant",
        ),
        UniqueConstraint("tenant_id", "expense_id", "position", name="uq_expense_splits_tenant_expense_position"),
        UniqueConstraint("tenant_id", "expense_id", "member_id", name="uq_expense_splits_tenant_expense_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(Integer, ForeignKey("ledger_members.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_expense_splits_tenant_expense_position", ExpenseSplit.tenant_id, ExpenseSplit.expense_id, ExpenseSplit.position)
Index("ix_expense_splits_tenant_public_id", ExpenseSplit.tenant_id, ExpenseSplit.public_id)
Index("ix_expense_splits_tenant_member", ExpenseSplit.tenant_id, ExpenseSplit.member_id)
