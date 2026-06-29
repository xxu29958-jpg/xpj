from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
Index("ix_budgets_tenant_archived", Budget.tenant_id, Budget.archived_at)
Index("ix_budget_categories_tenant_month", BudgetCategory.tenant_id, BudgetCategory.month)
Index("ix_budget_categories_tenant_category", BudgetCategory.tenant_id, BudgetCategory.category)


class Goal(Base):
    __tablename__ = "goals"
    # ADR-0049 §6 slice 6 widens this table from spending_limit-only to also carry
    # ``debt_repayment`` goals. A debt_repayment goal has no ``month`` / ``category``
    # / ``target_amount_cents`` (it links explicit Debt ids instead), so those
    # columns become nullable and the month / target CHECKs are gated to the
    # spending_limit type. The two partial-unique scope indexes (below) gain a
    # ``goal_type = 'spending_limit'`` predicate so the "one active goal per
    # tenant/month/scope" rule does NOT wrongly cap a tenant at one active
    # debt_repayment goal — those are allowed to coexist (and have NULL month).
    __table_args__ = (
        CheckConstraint(
            "goal_type IN ('spending_limit', 'debt_repayment')", name="ck_goals_type_valid"
        ),
        CheckConstraint("period IN ('monthly')", name="ck_goals_period_valid"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_goals_status_valid"),
        # month / target only constrain spending_limit goals; a debt_repayment
        # goal stores NULL for both.
        CheckConstraint(
            "goal_type <> 'spending_limit' OR length(month) = 7", name="ck_goals_month_format"
        ),
        CheckConstraint(
            "goal_type <> 'spending_limit' OR target_amount_cents > 0",
            name="ck_goals_target_positive",
        ),
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
    # NULL for debt_repayment goals (ADR-0049 §6); always set for spending_limit.
    month: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # NULL for debt_repayment goals; > 0 for spending_limit (CHECK above).
    target_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # ADR-0049 §6 debt_repayment goals only. ``goal_version`` is bumped each time
    # the linked Debt set changes (DebtGoalLink rows are written per version, old
    # versions are frozen). Achievement is latched per goal version: when every
    # linked Debt of the CURRENT version is cleared, ``achieved_at`` /
    # ``achieved_version`` are stamped once and stay sticky even if a linked Debt
    # later reopens. spending_limit goals leave ``goal_version`` at 1 and
    # ``achieved_*`` NULL.
    goal_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    achieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    achieved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ADR-0049 §6/F13 integrity review: the goal_version for which the user
    # explicitly acknowledged ("keep for audit") an achieved version that carries a
    # debt-voided linked Debt. While `integrity_reviewed_version == goal_version` the
    # integrity-review `needs_review` flag is cleared for that version; a later link
    # change bumps goal_version so a still-voided new version must be re-acknowledged.
    integrity_reviewed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ADR-0049 §7.0 / 8e-6c: optional payoff DEADLINE for a pure-external debt_repayment
    # goal (a calendar day; ``Date`` not ``DateTime`` sidesteps the tz-strip hazards). Drives
    # the On track / Ahead / At risk three-state (projected payoff month vs this month). NULL =
    # no deadline set (and always NULL for spending_limit / member / mixed goals). Orthogonal
    # to the type CHECKs and the two scope indexes, so it is a single-step nullable add.
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)


Index("ix_goals_tenant_month_status", Goal.tenant_id, Goal.month, Goal.status)
Index("ix_goals_tenant_category_month", Goal.tenant_id, Goal.category, Goal.month)
Index("ix_goals_tenant_public_id", Goal.tenant_id, Goal.public_id)
# ADR-0049 §6: the two "one active goal per (tenant, month, scope)" partial-unique
# indexes are gated to ``goal_type = 'spending_limit'`` so they do NOT apply to
# debt_repayment goals — those have NULL month and a tenant may keep several
# active at once. The migration's ``postgresql_where`` text is, by manual
# convention, kept equivalent to these predicates (the ``_audit_partial_index_pg_where``
# lane only checks that a partial UNIQUE declares ``postgresql_where`` at all).
Index(
    "uq_goals_active_total_scope",
    Goal.tenant_id,
    Goal.month,
    Goal.goal_type,
    Goal.period,
    unique=True,
    postgresql_where=(
        (Goal.status == "active")
        & Goal.category.is_(None)
        & (Goal.goal_type == "spending_limit")
    ),
)
Index(
    "uq_goals_active_category_scope",
    Goal.tenant_id,
    Goal.month,
    Goal.goal_type,
    Goal.period,
    Goal.category,
    unique=True,
    postgresql_where=(
        (Goal.status == "active")
        & Goal.category.is_not(None)
        & (Goal.goal_type == "spending_limit")
    ),
)


class DebtGoalLink(Base):
    """ADR-0049 §6: one (goal_version, Debt) membership row for a debt_repayment goal.

    The linked Debt set is FROZEN per goal version: every time the set changes the
    parent ``Goal.goal_version`` is bumped and a fresh batch of ``DebtGoalLink`` rows
    is written for the new version while the old version's rows are kept (so an older
    achieved version is never retroactively re-evaluated). The evaluator only ever
    reads the rows of the goal's CURRENT ``goal_version``. ``UNIQUE(goal_id,
    goal_version, debt_id)`` makes a Debt appear at most once in a version's set.

    No ``public_id`` — a link is internal bookkeeping, never addressed by clients
    (they address Debts by ``Debt.public_id`` and goals by ``Goal.public_id``).
    Tenant isolation rides the parent ``Goal`` / ``Debt`` rows, both of which the
    service confirms belong to the acting tenant before a link is written.
    """

    __tablename__ = "debt_goal_links"
    __table_args__ = (
        UniqueConstraint(
            "goal_id", "goal_version", "debt_id", name="uq_debt_goal_links_goal_version_debt"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("goals.id", name="fk_debt_goal_links_goal"), nullable=False, index=True
    )
    goal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    debt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("debts.id", name="fk_debt_goal_links_debt"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_debt_goal_links_goal_version", DebtGoalLink.goal_id, DebtGoalLink.goal_version)


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
