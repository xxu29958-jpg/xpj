"""Cash-backed purposes share budgets, but never create another asset or Expense."""
from datetime import datetime

from sqlalchemy import DDL, JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.currency_catalog import CURRENCY_SQL_LIST
from app.database_model_registry import Base
from app.money_contract import money_check_constraints_for_table
from app.services.time_service import now_utc


class EnvelopeBook(Base):
    __tablename__ = "envelope_books"
    __table_args__ = (
        CheckConstraint("row_version > 0", name="ck_envelope_book_version"),
        CheckConstraint(f"home_currency_code IN ({CURRENCY_SQL_LIST})", name="ck_envelope_book_currency"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), primary_key=True)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class EnvelopeSource(Base):
    __tablename__ = "envelope_sources"
    # A real cash account can back only one ledger's envelope pool.
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("financial_accounts.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("envelope_books.tenant_id"), nullable=False, index=True)


class EnvelopeAllocation(Base):
    __tablename__ = "envelope_allocations"
    __table_args__ = (
        *money_check_constraints_for_table("envelope_allocations"),
        CheckConstraint("month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_envelope_allocation_month"),
        CheckConstraint("purpose IN ('spending','savings','buffer') OR purpose LIKE 'category:%'",
                        name="ck_envelope_allocation_purpose"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("envelope_books.tenant_id"), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(80), primary_key=True)
    allocated_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EnvelopeRevision(Base):
    __tablename__ = "envelope_revisions"
    __table_args__ = (CheckConstraint("row_version > 0", name="ck_envelope_revision_version"),)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("envelope_books.tenant_id"), primary_key=True)
    row_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # Captured user intent only; private account balances never enter this history.
    allocation_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


ENVELOPE_GUARDS_SQL = """
CREATE OR REPLACE FUNCTION ticketbox_envelope_currency_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    IF NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
        RAISE EXCEPTION 'envelope currency cannot relabel assigned amounts' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_envelope_currency_guard BEFORE UPDATE ON envelope_books
    FOR EACH ROW EXECUTE FUNCTION ticketbox_envelope_currency_guard();
CREATE OR REPLACE FUNCTION ticketbox_envelope_revision_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'envelope revisions are immutable' USING ERRCODE = '55000';
END $$;
CREATE TRIGGER trg_envelope_revision_immutable BEFORE UPDATE OR DELETE ON envelope_revisions
    FOR EACH ROW EXECUTE FUNCTION ticketbox_envelope_revision_immutable();
CREATE TRIGGER trg_envelope_revision_no_truncate BEFORE TRUNCATE ON envelope_revisions
    FOR EACH STATEMENT EXECUTE FUNCTION ticketbox_envelope_revision_immutable();
"""
event.listen(EnvelopeRevision.__table__, "after_create", DDL(ENVELOPE_GUARDS_SQL).execute_if(dialect="postgresql"))
