from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class CategoryRule(Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_category_rules_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
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
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # ADR-0038 undo: soft-delete tombstone. Hidden from every read while set;
    # restorable via the undo endpoint until cleanup purges it past retention.
    # Indexed via the module-level composite below (not column-level, to keep
    # create_all and the startup migrator declaring the same index set).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RuleApplicationBatch(Base):
    __tablename__ = "rule_application_batches"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_rule_application_batches_id_tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_rule_application_batches_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="applied", nullable=False, index=True)
    pending_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    actor_device_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("devices.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleApplicationChange(Base):
    __tablename__ = "rule_application_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id", "tenant_id"],
            ["rule_application_batches.id", "rule_application_batches.tenant_id"],
            name="fk_rule_application_changes_batch_tenant",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_rule_application_changes_expense_tenant",
        ),
    )

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


Index("ix_category_rules_tenant_priority_id", CategoryRule.tenant_id, CategoryRule.priority, CategoryRule.id)
Index("ix_category_rules_tenant_enabled_priority", CategoryRule.tenant_id, CategoryRule.enabled, CategoryRule.priority, CategoryRule.id)
Index("ix_category_rules_tenant_deleted", CategoryRule.tenant_id, CategoryRule.deleted_at)
Index("ix_rule_application_batches_tenant_created_at", RuleApplicationBatch.tenant_id, RuleApplicationBatch.created_at)
Index("ix_rule_application_batches_tenant_status", RuleApplicationBatch.tenant_id, RuleApplicationBatch.status)
Index("ix_rule_application_changes_tenant_batch", RuleApplicationChange.tenant_id, RuleApplicationChange.batch_id)
Index("ix_rule_application_changes_tenant_expense", RuleApplicationChange.tenant_id, RuleApplicationChange.expense_id)
