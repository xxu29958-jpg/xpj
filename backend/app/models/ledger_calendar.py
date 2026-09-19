"""Immutable ledger calendar rules and ledger-scoped time evidence constraints."""

from datetime import datetime

from sqlalchemy import DDL, CheckConstraint, DateTime, ForeignKey, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class LedgerCalendarRevision(Base):
    __tablename__ = "ledger_calendar_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_ledger_calendar_revision_positive"),
        CheckConstraint("char_length(timezone_name) > 0", name="ck_ledger_calendar_timezone_present"),
        CheckConstraint("char_length(basis) > 0", name="ck_ledger_calendar_basis_present"),
    )

    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey("ledgers.ledger_id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    timezone_name: Mapped[str] = mapped_column(String(128), nullable=False)
    basis: Mapped[str] = mapped_column(String(64), nullable=False)
    adopted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True)


def time_evidence_constraints(table: str) -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("calendar_revision IS NULL OR calendar_revision >= 1", name=f"ck_{table}_calendar_positive"),
        CheckConstraint(
            "time_precision IS NULL OR time_precision IN ('instant', 'date_only', 'unknown')",
            name=f"ck_{table}_time_precision",
        ),
        CheckConstraint(
            "source_utc_offset_seconds IS NULL OR source_utc_offset_seconds BETWEEN -86399 AND 86399",
            name=f"ck_{table}_source_offset",
        ),
        CheckConstraint(
            "time_precision IS DISTINCT FROM 'date_only' OR source_utc_offset_seconds IS NULL",
            name=f"ck_{table}_date_only_offset",
        ),
    )


event.listen(
    LedgerCalendarRevision.__table__, "after_create",
    DDL("CREATE OR REPLACE FUNCTION ticketbox_reject_calendar_revision_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'ledger_calendar_revisions is append-only' "
        "USING ERRCODE = '55000'; END $$").execute_if(dialect="postgresql"),
)
event.listen(
    LedgerCalendarRevision.__table__, "after_create",
    DDL("CREATE TRIGGER trg_ledger_calendar_revisions_append_only BEFORE UPDATE OR DELETE OR TRUNCATE "
        "ON ledger_calendar_revisions FOR EACH STATEMENT "
        "EXECUTE FUNCTION ticketbox_reject_calendar_revision_mutation()").execute_if(dialect="postgresql"),
)
