from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    identity_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cloud_subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Ledger(Base):
    __tablename__ = "ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ledger_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerMember(Base):
    __tablename__ = "ledger_members"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member', 'viewer')", name="ck_ledger_members_role_valid"),
        UniqueConstraint("ledger_id", "account_id", name="uq_ledger_member_ledger_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadLink(Base):
    __tablename__ = "upload_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False, index=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    default_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    device_name_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Invitation(Base):
    """Family ledger invitation token.

    Owner mints a one-time token bound to a (ledger_id, role). Plain token
    is returned to owner once and never persisted; only ``token_hash``
    (sha256 of the plain token) is stored. ``role`` must be ``member`` or
    ``viewer`` — owner role is granted only via initial ledger creation or
    explicit owner transfer.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("role IN ('member', 'viewer')", name="ck_invitations_role_invitable"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    ledger_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    note: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LedgerAuditLog(Base):
    __tablename__ = "ledger_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    ledger_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ledgers.ledger_id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    target_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    target_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    invitation_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    previous_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result: Mapped[str] = mapped_column(String(32), default="success", nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_ledger_audit_logs_ledger_created_at", LedgerAuditLog.ledger_id, LedgerAuditLog.created_at)
Index("ix_ledger_audit_logs_ledger_action", LedgerAuditLog.ledger_id, LedgerAuditLog.action)


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
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
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
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_recurring_items_tenant_status_next", RecurringItem.tenant_id, RecurringItem.status, RecurringItem.next_expected_date)
Index("ix_recurring_items_tenant_merchant", RecurringItem.tenant_id, RecurringItem.merchant_key)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("total_amount_cents >= 0", name="ck_budgets_total_non_negative"),
        CheckConstraint("non_monthly_amount_cents >= 0", name="ck_budgets_non_monthly_non_negative"),
        CheckConstraint("length(month) = 7", name="ck_budgets_month_format"),
        UniqueConstraint("tenant_id", "month", name="uq_budgets_tenant_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    total_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    non_monthly_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rollover_amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    excluded_categories: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class BudgetCategory(Base):
    __tablename__ = "budget_categories"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_budget_categories_amount_non_negative"),
        CheckConstraint("length(month) = 7", name="ck_budget_categories_month_format"),
        UniqueConstraint("tenant_id", "month", "category", name="uq_budget_categories_tenant_month_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_budgets_tenant_month", Budget.tenant_id, Budget.month)
Index("ix_budget_categories_tenant_month", BudgetCategory.tenant_id, BudgetCategory.month)
Index("ix_budget_categories_tenant_category", BudgetCategory.tenant_id, BudgetCategory.category)


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)
    amount_min_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_max_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_contains: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tag_contains: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class RuleApplicationBatch(Base):
    __tablename__ = "rule_application_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="applied", nullable=False, index=True)
    pending_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    actor_device_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("devices.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleApplicationChange(Base):
    __tablename__ = "rule_application_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("rule_application_batches.id"), nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    matched_keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_category: Mapped[str] = mapped_column(String(64), nullable=False)
    after_category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="applied", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "alias_key", name="uq_merchant_aliases_tenant_alias_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    canonical_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tags_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class ExpenseTag(Base):
    __tablename__ = "expense_tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_id", "tag_id", name="uq_expense_tags_tenant_expense_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


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
Index("ix_category_rules_tenant_enabled_priority", CategoryRule.tenant_id, CategoryRule.enabled, CategoryRule.priority, CategoryRule.id)
Index("ix_rule_application_batches_tenant_created_at", RuleApplicationBatch.tenant_id, RuleApplicationBatch.created_at)
Index("ix_rule_application_batches_tenant_status", RuleApplicationBatch.tenant_id, RuleApplicationBatch.status)
Index("ix_rule_application_changes_tenant_batch", RuleApplicationChange.tenant_id, RuleApplicationChange.batch_id)
Index("ix_rule_application_changes_tenant_expense", RuleApplicationChange.tenant_id, RuleApplicationChange.expense_id)
Index("ix_merchant_aliases_tenant_canonical", MerchantAlias.tenant_id, MerchantAlias.canonical_key)
Index("ix_merchant_aliases_tenant_alias_key", MerchantAlias.tenant_id, MerchantAlias.alias_key)
Index("ix_tags_tenant_key", Tag.tenant_id, Tag.key)
Index("ix_tags_tenant_name", Tag.tenant_id, Tag.name)
Index("ix_expense_tags_tenant_expense", ExpenseTag.tenant_id, ExpenseTag.expense_id)
Index("ix_expense_tags_tenant_tag", ExpenseTag.tenant_id, ExpenseTag.tag_id)
Index("ix_duplicate_ignores_tenant_pair_kind", DuplicateIgnore.tenant_id, DuplicateIgnore.expense_id, DuplicateIgnore.duplicate_of_id, DuplicateIgnore.kind)
