from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_budgets_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
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
        ForeignKeyConstraint(
            ["tenant_id", "month"],
            ["budgets.tenant_id", "budgets.month"],
            name="fk_budget_categories_budget_month",
        ),
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


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("goal_type IN ('spending_limit')", name="ck_goals_type_valid"),
        CheckConstraint("period IN ('monthly')", name="ck_goals_period_valid"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_goals_status_valid"),
        CheckConstraint("length(month) = 7", name="ck_goals_month_format"),
        CheckConstraint("target_amount_cents > 0", name="ck_goals_target_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_goals_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    goal_type: Mapped[str] = mapped_column(String(32), default="spending_limit", nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(32), default="monthly", nullable=False, index=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_goals_tenant_month_status", Goal.tenant_id, Goal.month, Goal.status)
Index("ix_goals_tenant_category_month", Goal.tenant_id, Goal.category, Goal.month)
Index("ix_goals_tenant_public_id", Goal.tenant_id, Goal.public_id)
Index(
    "uq_goals_active_total_scope",
    Goal.tenant_id,
    Goal.month,
    Goal.goal_type,
    Goal.period,
    unique=True,
    postgresql_where=(Goal.status == "active") & Goal.category.is_(None),
)
Index(
    "uq_goals_active_category_scope",
    Goal.tenant_id,
    Goal.month,
    Goal.goal_type,
    Goal.period,
    Goal.category,
    unique=True,
    postgresql_where=(Goal.status == "active") & Goal.category.is_not(None),
)


class DashboardCardPreference(Base):
    __tablename__ = "dashboard_card_preferences"
    __table_args__ = (
        CheckConstraint("surface IN ('android', 'web')", name="ck_dashboard_cards_surface_valid"),
        CheckConstraint("position >= 0", name="ck_dashboard_cards_position_non_negative"),
        UniqueConstraint("tenant_id", "surface", "card_key", name="uq_dashboard_cards_tenant_surface_key"),
        UniqueConstraint("tenant_id", "surface", "position", name="uq_dashboard_cards_tenant_surface_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_dashboard_cards_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    card_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index(
    "ix_dashboard_cards_tenant_surface_position",
    DashboardCardPreference.tenant_id,
    DashboardCardPreference.surface,
    DashboardCardPreference.position,
)
Index(
    "ix_dashboard_cards_tenant_surface_key",
    DashboardCardPreference.tenant_id,
    DashboardCardPreference.surface,
    DashboardCardPreference.card_key,
)
