from __future__ import annotations

from io import BytesIO

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import CsvImportRow, Expense
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
)


def _csv_bytes(row_count: int) -> BytesIO:
    lines = ["amount_yuan,merchant,category,note"]
    lines.extend(
        f"{index}.00,Merchant {index},餐饮,note {index}"
        for index in range(1, row_count + 1)
    )
    return BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def test_csv_import_integrity_error_marks_only_failed_row_insert_failed(
    identity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del identity
    import app.services.csv_import_batch_service._apply as apply_mod

    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="partial-integrity.csv",
            file_obj=_csv_bytes(3),
        )
        public_id = batch.public_id
        batch_id = batch.id

    real_sync_expense_tags = apply_mod.sync_expense_tags

    def fail_second_row(db, expense):
        if expense.merchant == "Merchant 2":
            raise IntegrityError("insert expense tag", {}, ValueError("tag conflict"))
        return real_sync_expense_tags(db, expense)

    monkeypatch.setattr(apply_mod, "sync_expense_tags", fail_second_row)

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 2
        assert applied.remaining_valid_rows == 0
        assert applied.batch.status == "applied_with_errors"

        rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
                .order_by(CsvImportRow.line_number.asc())
            )
        )
        assert [row.status for row in rows] == ["applied", "insert_failed", "applied"]
        assert rows[1].expense_id is None
        assert rows[1].error_code == "insert_failed"
        assert all(row.apply_token is None for row in rows)

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.merchant.in_(("Merchant 1", "Merchant 3")))
        )
        assert inserted == 2
