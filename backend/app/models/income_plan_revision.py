"""Immutable income estimates; the plan row is their current OCC projection."""

from datetime import date, datetime

from sqlalchemy import (
    DDL,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.models.financial_planning import MonthlyIncomePlan
from app.money_contract_types import MONEY_MINOR_MAX


class IncomePlanRevision(Base):
    __tablename__ = "income_plan_revisions"
    __table_args__ = (
        CheckConstraint("home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')", name="ck_income_revision_currency"),
        ForeignKeyConstraint(
            ["plan_id", "tenant_id"], ["monthly_income_plans.id", "monthly_income_plans.tenant_id"],
            name="fk_income_plan_revision_plan_tenant", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "plan_id", "revision_number", name="uq_income_plan_revision_number"),
        CheckConstraint("revision_number >= 1", name="ck_income_plan_revision_number"),
        CheckConstraint(
            "(effective_month IS NULL OR EXTRACT(DAY FROM effective_month) = 1) AND "
            "(intent_month IS NULL OR EXTRACT(DAY FROM intent_month) = 1)", name="ck_income_plan_revision_month",
        ),
        CheckConstraint("amount_cents BETWEEN 0 AND " + str(MONEY_MINOR_MAX), name="ck_income_plan_revision_money"),
        CheckConstraint("pay_day BETWEEN 1 AND 31", name="ck_income_plan_revision_pay_day"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_income_plan_revision_status"),
        CheckConstraint(
            "(frequency = 'monthly' AND income_month IS NULL) OR "
            "(frequency = 'one_time' AND income_month IS NOT NULL)",
            name="ck_income_plan_revision_frequency",
        ),
        CheckConstraint(
            "change_kind IN ('baseline', 'create', 'edit', 'archive', 'restore') AND "
            "((change_kind = 'baseline' AND effective_month IS NULL AND intent_month IS NULL) OR "
            "(change_kind <> 'baseline' AND effective_month IS NOT NULL AND intent_month IS NOT NULL))",
            name="ck_income_plan_revision_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    intent_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    income_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    home_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pay_day: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_income_plan_revision_actor", ondelete="RESTRICT"), nullable=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


event.listen(
    IncomePlanRevision.__table__, "after_create",
    DDL("""
        CREATE OR REPLACE FUNCTION ticketbox_income_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NULL
               AND NEW.home_currency_code IS NOT NULL
               AND (to_jsonb(NEW) - 'home_currency_code') IS NOT DISTINCT FROM (to_jsonb(OLD) - 'home_currency_code')
               AND EXISTS (
                   SELECT 1 FROM installation_currency_bindings
                   WHERE singleton_id = 1 AND state = 'ACTIVE' AND home_currency_code = NEW.home_currency_code
                     AND current_setting('xpj.currency_writer', true) = currency_contract_version::text || ':' || binding_revision::text
               ) THEN RETURN NEW;
            END IF;
            RAISE EXCEPTION 'income plan revisions are immutable' USING ERRCODE = '55000';
        END $$;
        CREATE TRIGGER trg_income_plan_revision_immutable
        BEFORE UPDATE OR DELETE ON income_plan_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_income_revision_immutable();
    """).execute_if(dialect="postgresql"),
)


for _table in (MonthlyIncomePlan.__table__, IncomePlanRevision.__table__):
    event.listen(_table, "after_create", DDL("""
        CREATE OR REPLACE FUNCTION ticketbox_income_currency_required()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'income requires its captured currency' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_income_currency_required BEFORE INSERT OR UPDATE ON %(table)s
        FOR EACH ROW EXECUTE FUNCTION ticketbox_income_currency_required();
    """).execute_if(dialect="postgresql"))
