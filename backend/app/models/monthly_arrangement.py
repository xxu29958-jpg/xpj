"""One current monthly intention and immutable, currency-captured revisions."""

from datetime import datetime

from sqlalchemy import (
    DDL,
    BigInteger,
    CheckConstraint,
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
from app.monthly_arrangement_money_contract import monthly_arrangement_money_checks


class MonthlyArrangement(Base):
    __tablename__ = "monthly_arrangements"
    __table_args__ = (
        *monthly_arrangement_money_checks("monthly_arrangements"),
        CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_monthly_arrangement_month"),
        CheckConstraint("home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')", name="ck_monthly_arrangement_currency"),
        CheckConstraint("row_version >= 1", name="ck_monthly_arrangement_version"),
        UniqueConstraint("tenant_id", "month", name="uq_monthly_arrangement_tenant_month"),
        UniqueConstraint("id", "tenant_id", name="uq_monthly_arrangement_id_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id", name="fk_monthly_arrangement_ledger"), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    savings_target_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_buffer_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MonthlyArrangementRevision(Base):
    __tablename__ = "monthly_arrangement_revisions"
    __table_args__ = (
        *monthly_arrangement_money_checks("monthly_arrangement_revisions"),
        ForeignKeyConstraint(["arrangement_id", "tenant_id"], ["monthly_arrangements.id", "monthly_arrangements.tenant_id"],
            name="fk_monthly_arrangement_revision_parent", ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "arrangement_id", "row_version", name="uq_monthly_arrangement_revision_version"),
        CheckConstraint("row_version >= 1", name="ck_monthly_arrangement_revision_version"),
        CheckConstraint("home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')", name="ck_monthly_arrangement_revision_currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    arrangement_id: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    savings_target_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_buffer_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(Integer,
        ForeignKey("accounts.id", name="fk_monthly_arrangement_revision_actor", ondelete="RESTRICT"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


ARRANGEMENT_CURRENCY_GUARD_SQL = """
    CREATE OR REPLACE FUNCTION ticketbox_monthly_arrangement_currency_guard()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
            RAISE EXCEPTION 'monthly arrangement currency cannot relabel saved amounts' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER trg_monthly_arrangement_currency_guard BEFORE UPDATE ON monthly_arrangements
    FOR EACH ROW EXECUTE FUNCTION ticketbox_monthly_arrangement_currency_guard();
"""
ARRANGEMENT_REVISION_GUARD_SQL = """
    CREATE OR REPLACE FUNCTION ticketbox_monthly_arrangement_revision_immutable()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'monthly arrangement revisions are immutable' USING ERRCODE = '55000';
    END $$;
    CREATE TRIGGER trg_monthly_arrangement_revision_immutable BEFORE UPDATE OR DELETE ON monthly_arrangement_revisions
    FOR EACH ROW EXECUTE FUNCTION ticketbox_monthly_arrangement_revision_immutable();
    CREATE TRIGGER trg_monthly_arrangement_revision_no_truncate BEFORE TRUNCATE ON monthly_arrangement_revisions
    FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_monthly_arrangement_revision_immutable();
"""
event.listen(MonthlyArrangement.__table__, "after_create", DDL(ARRANGEMENT_CURRENCY_GUARD_SQL).execute_if(dialect="postgresql"))
event.listen(MonthlyArrangementRevision.__table__, "after_create", DDL(ARRANGEMENT_REVISION_GUARD_SQL).execute_if(dialect="postgresql"))
