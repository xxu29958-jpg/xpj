"""User-declared monthly income lines for v1.1 budget formula.

Sister to ``recurring_items`` but in the opposite direction:
``RecurringItem`` records **outgoing** subscriptions / bills that the
backend has identified from history. ``MonthlyIncomePlan`` records
**incoming** money the user has typed in during onboarding ("我的工资 X
元，每月 10 号"). The two together feed the "本月可自由支配" formula:

    discretionary = sum(active income plans)
                  - sum(active recurring items expected this month)
                  - savings target
                  - reserved buffer

No automatic detection — income arrival patterns are too noisy to infer
safely, and getting it wrong is the kind of error that erodes user trust.
The user types it; we just remember.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class MonthlyIncomePlan(Base):
    """One income line per row (multiple-job households can record more
    than one). All amounts in cents to stay consistent with the rest of
    the project (ENGINEERING_RULES §3)."""

    __tablename__ = "monthly_income_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_monthly_income_plans_status_valid",
        ),
        CheckConstraint(
            "pay_day >= 1 AND pay_day <= 31",
            name="ck_monthly_income_plans_pay_day_range",
        ),
        CheckConstraint(
            "amount_cents >= 0",
            name="ck_monthly_income_plans_amount_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36),
        default=lambda: str(uuid4()),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_monthly_income_plans_tenant"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    # Free-form short label the user types: "我的工资" / "副业" / "房租".
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    # Coarse classifier for the AI advisor — value not enforced here so
    # we don't break the row when a new source type appears mid-version.
    source_type: Mapped[str] = mapped_column(String(32), default="salary", nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    pay_day: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


Index(
    "ix_monthly_income_plans_tenant_status",
    MonthlyIncomePlan.tenant_id,
    MonthlyIncomePlan.status,
)
