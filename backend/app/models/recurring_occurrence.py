"""Planning associations; payments remain exclusively owned by Expense."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    DDL,
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
from app.services.time_service import now_utc


class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"
    __table_args__ = (
        ForeignKeyConstraint(
            ["series_id", "tenant_id"], ["recurring_items.id", "recurring_items.tenant_id"],
            name="fk_recurring_occurrences_series_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrences_expense_tenant", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "expense_id", name="uq_recurring_occurrences_payment"),
        CheckConstraint("EXTRACT(DAY FROM period_start) = 1", name="ck_recurring_occurrences_month"),
        CheckConstraint("row_version >= 1", name="ck_recurring_occurrences_version"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    expense_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class RecurringOccurrenceRevision(Base):
    __tablename__ = "recurring_occurrence_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "series_id", "period_start"],
            ["recurring_occurrences.tenant_id", "recurring_occurrences.series_id", "recurring_occurrences.period_start"],
            name="fk_recurring_occurrence_revisions_occurrence", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["previous_expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrence_revisions_previous_payment", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"],
            name="fk_recurring_occurrence_revisions_payment", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "series_id", "period_start", "revision_number", name="uq_recurring_occurrence_revision"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_recurring_occurrence_revision_intent"),
        CheckConstraint("revision_number >= 1", name="ck_recurring_occurrence_revisions_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    series_id: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_expense_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expense_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_recurring_occurrence_revision_actor", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


event.listen(
    RecurringOccurrenceRevision.__table__, "after_create",
    DDL("""
        CREATE OR REPLACE FUNCTION ticketbox_recurring_revision_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'recurring occurrence revisions are immutable';
        END $$;
        CREATE TRIGGER trg_recurring_occurrence_revision_immutable
        BEFORE UPDATE OR DELETE ON recurring_occurrence_revisions
        FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_revision_immutable();
    """).execute_if(dialect="postgresql"),
)
