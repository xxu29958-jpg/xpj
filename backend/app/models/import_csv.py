from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.fx_constants import DEFAULT_HOME_CURRENCY_CODE
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


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
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="parsed", nullable=False, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_csv_import_batches_tenant_public_id", CsvImportBatch.tenant_id, CsvImportBatch.public_id)
Index("ix_csv_import_batches_tenant_status_created_at", CsvImportBatch.tenant_id, CsvImportBatch.status, CsvImportBatch.created_at)


class CsvImportRow(Base):
    __tablename__ = "csv_import_rows"
    __table_args__ = (
        CheckConstraint("line_number >= 2", name="ck_csv_import_rows_line_number_valid"),
        CheckConstraint(
            "status IN ('valid', 'error', 'applying', 'applied', 'insert_failed')",
            name="ck_csv_import_rows_status_valid",
        ),
        CheckConstraint("amount_cents IS NULL OR amount_cents >= 0", name="ck_csv_import_rows_amount_non_negative"),
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
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("csv_import_batches.id"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_currency_code: Mapped[str] = mapped_column(
        String(3),
        default=DEFAULT_HOME_CURRENCY_CODE,
        nullable=False,
    )
    original_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


Index("ix_csv_import_rows_tenant_batch_line", CsvImportRow.tenant_id, CsvImportRow.batch_id, CsvImportRow.line_number)
Index("ix_csv_import_rows_tenant_batch_status", CsvImportRow.tenant_id, CsvImportRow.batch_id, CsvImportRow.status)
