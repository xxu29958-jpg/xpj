from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.money_contract import money_check_constraints_for_table
from app.services.time_service import now_utc
from app.tenant_contract import DEFAULT_TENANT_ID


class CsvImportBatch(Base):
    __tablename__ = "csv_import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('parsed', 'parsed_with_errors', 'applying', 'applied', 'applied_with_errors')",
            name="ck_csv_import_batches_status_valid",
        ),
        CheckConstraint("total_rows >= 0", name="ck_csv_import_batches_total_rows_non_negative"),
        CheckConstraint("valid_rows >= 0", name="ck_csv_import_batches_valid_rows_non_negative"),
        CheckConstraint("error_rows >= 0", name="ck_csv_import_batches_error_rows_non_negative"),
        CheckConstraint("applied_rows >= 0", name="ck_csv_import_batches_applied_rows_non_negative"),
        CheckConstraint("inserted_count >= 0", name="ck_csv_import_batches_inserted_count_non_negative"),
        UniqueConstraint("id", "tenant_id", name="uq_csv_import_batches_id_tenant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_csv_import_batches_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="parsed", nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    apply_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_csv_import_batches_tenant_public_id", CsvImportBatch.tenant_id, CsvImportBatch.public_id)
Index("ix_csv_import_batches_tenant_status_created_at", CsvImportBatch.tenant_id, CsvImportBatch.status, CsvImportBatch.created_at)


class CsvImportRow(Base):
    __tablename__ = "csv_import_rows"
    __table_args__ = (
        *money_check_constraints_for_table("csv_import_rows"),
        CheckConstraint("home_currency_code IN ('CNY', 'USD', 'EUR', 'GBP', 'JPY', 'HKD', 'KRW')", name="ck_csv_import_rows_home_currency"),
        CheckConstraint("line_number >= 2", name="ck_csv_import_rows_line_number_valid"),
        CheckConstraint(
            "status IN ('valid', 'error', 'applying', 'applied', 'insert_failed', 'review', 'matched', 'conflict')",
            name="ck_csv_import_rows_status_valid",
        ),
        ForeignKeyConstraint(
            ["batch_id", "tenant_id"],
            ["csv_import_batches.id", "csv_import_batches.tenant_id"],
            name="fk_csv_import_rows_batch_tenant",
        ),
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_csv_import_rows_expense_tenant",
        ),
        UniqueConstraint("tenant_id", "batch_id", "line_number", name="uq_csv_import_rows_tenant_batch_line"),
        UniqueConstraint("id", "tenant_id", name="uq_csv_import_rows_id_tenant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("csv_import_batches.id"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    apply_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_kind: Mapped[str] = mapped_column(String(32), default="expense", server_default="expense", nullable=False)
    offset_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_event_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_root_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accounting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stream_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lineage_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lineage_home_net_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_input: Mapped[dict[str, str] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Legacy unknown context remains NULL until the existing Owner adoption.
    home_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_currency_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    original_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exchange_rate_to_cny: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="其他", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="CSV导入", nullable=False)
    expense_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class CsvImportEvent(Base):
    """Ledger-local provenance/result shared by repeated native import rows.

    This is an import receipt, not another financial event. A pending offset has
    no offset_id until the canonical Facts command and this receipt commit together.
    The first saved row retains file evidence, including the claimed FX source.
    """

    __tablename__ = "csv_import_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_kind", "source_event_public_id", name="uq_csv_import_events_source"),
        CheckConstraint("entry_kind IN ('expense', 'offset')", name="ck_csv_import_events_kind"),
        CheckConstraint("offset_id IS NULL OR (entry_kind = 'offset' AND expense_id IS NOT NULL)", name="ck_csv_import_events_result"),
        CheckConstraint("source_row_id IS NOT NULL OR (entry_kind = 'expense' AND expense_id IS NOT NULL AND offset_id IS NULL)", name="ck_csv_import_events_source"),
        ForeignKeyConstraint(["source_row_id", "tenant_id"], ["csv_import_rows.id", "csv_import_rows.tenant_id"], name="fk_csv_import_events_source_row"),
        ForeignKeyConstraint(["expense_id", "tenant_id"], ["expenses.id", "expenses.tenant_id"], name="fk_csv_import_events_expense"),
        ForeignKeyConstraint(["offset_id", "tenant_id"], ["expense_offset_facts.id", "expense_offset_facts.tenant_id"], name="fk_csv_import_events_offset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # NULL only when a reviewed offset explicitly associates a source root
    # with an existing local purchase before that purchase's own row arrives.
    source_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expense_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_csv_import_rows_source_event", CsvImportRow.tenant_id, CsvImportRow.entry_kind, CsvImportRow.source_event_public_id)
Index("ix_csv_import_rows_tenant_batch_line", CsvImportRow.tenant_id, CsvImportRow.batch_id, CsvImportRow.line_number)
Index("ix_csv_import_rows_tenant_batch_status", CsvImportRow.tenant_id, CsvImportRow.batch_id, CsvImportRow.status)
Index(
    "uq_csv_import_rows_tenant_expense_id",
    CsvImportRow.tenant_id,
    CsvImportRow.expense_id,
    unique=True,
    postgresql_where=CsvImportRow.expense_id.is_not(None),
)

event.listen(
    CsvImportRow.__table__, "after_create",
    DDL("""
        CREATE OR REPLACE FUNCTION ticketbox_csv_row_currency_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.home_currency_code IS NULL THEN
                RAISE EXCEPTION 'CSV row requires its captured currency' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.home_currency_code IS NOT NULL
               AND NEW.home_currency_code IS DISTINCT FROM OLD.home_currency_code THEN
                RAISE EXCEPTION 'CSV row currency is immutable' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER trg_csv_row_currency BEFORE INSERT OR UPDATE ON csv_import_rows
        FOR EACH ROW EXECUTE FUNCTION ticketbox_csv_row_currency_guard();
    """).execute_if(dialect="postgresql"),
)
