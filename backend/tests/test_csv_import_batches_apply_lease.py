from __future__ import annotations

from datetime import timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.errors import AppError
from app.models import CsvImportBatch, CsvImportRow, Expense, LedgerMember
from app.services.csv_import_batch_service import (
    _claim_apply_lease,
    _claim_csv_import_rows,
    _refresh_claimed_csv_import_row,
    _resolve_csv_import_idempotency_conflict,
    apply_csv_import_batch,
    create_csv_import_batch,
)
from app.services.time_service import now_utc


def _csv_bytes(row_count: int) -> BytesIO:
    lines = ["amount_yuan,merchant,category,note"]
    lines.extend(f"{index}.00,Merchant {index},餐饮,note {index}" for index in range(1, row_count + 1))
    return BytesIO(("\n".join(lines) + "\n").encode("utf-8"))


def _demote_owner_ledger_to_viewer() -> None:
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()


def test_csv_import_apply_lease_is_atomically_claimed(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="lease.csv",
            file_obj=_csv_bytes(2),
        )
        public_id = batch.public_id

    with SessionLocal() as first_db, SessionLocal() as second_db:
        claimed = _claim_apply_lease(
            first_db,
            tenant_id="owner",
            public_id=public_id,
            apply_token="worker-a",
        )
        assert claimed.status == "applying"
        assert claimed.locked_until is not None

        with pytest.raises(AppError) as exc_info:
            _claim_apply_lease(
                second_db,
                tenant_id="owner",
                public_id=public_id,
                apply_token="worker-b",
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.error == "invalid_request"

    with SessionLocal() as db:
        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
        )
        assert inserted == 0


def test_csv_import_row_claim_recovers_stale_apply_after_batch_lease_expires(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="row-claim.csv",
            file_obj=_csv_bytes(2),
        )
        public_id = batch.public_id
        batch_id = batch.id
        claimed_ids = _claim_csv_import_rows(
            setup_db,
            tenant_id="owner",
            batch_id=batch_id,
            batch_size=1,
            apply_token="worker-a",
        )
        assert len(claimed_ids) == 1

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 1
        assert applied.remaining_valid_rows == 1

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 1

        rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
                .order_by(CsvImportRow.line_number.asc())
            )
        )
        assert sorted(row.status for row in rows) == ["applied", "applying"]

        with pytest.raises(AppError) as exc_info:
            apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=public_id,
                batch_size=10,
            )
        assert exc_info.value.status_code == 409

        inserted_after_retry = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted_after_retry == 1

        db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
            .where(CsvImportRow.status == "applying")
            .values(updated_at=now_utc() - timedelta(minutes=10))
        )
        db.commit()

        recovered = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert recovered.inserted_count == 1
        assert recovered.remaining_valid_rows == 0

        final_rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
            )
        )
        assert sorted(row.status for row in final_rows) == ["applied", "applied"]

        final_inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert final_inserted == 2


def test_csv_import_recovers_legacy_stale_applying_row_without_apply_token(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="legacy-row-token.csv",
            file_obj=_csv_bytes(2),
        )
        public_id = batch.public_id
        batch_id = batch.id
        row_id = setup_db.scalar(
            select(CsvImportRow.id)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
            .order_by(CsvImportRow.line_number.asc())
            .limit(1)
        )
        assert row_id is not None
        setup_db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.id == row_id)
            .values(
                status="applying",
                apply_token=None,
                updated_at=now_utc() - timedelta(minutes=10),
            )
        )
        setup_db.commit()

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 2
        assert applied.remaining_valid_rows == 0
        assert applied.batch.status == "applied"

        rows = list(
            db.scalars(
                select(CsvImportRow)
                .where(CsvImportRow.tenant_id == "owner")
                .where(CsvImportRow.batch_id == batch_id)
            )
        )
        assert sorted(row.status for row in rows) == ["applied", "applied"]
        assert all(row.apply_token is None for row in rows)


def test_csv_import_stale_worker_token_cannot_apply_after_reclaim(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="fence.csv",
            file_obj=_csv_bytes(1),
        )
        public_id = batch.public_id
        batch_id = batch.id
        row_ids = _claim_csv_import_rows(
            setup_db,
            tenant_id="owner",
            batch_id=batch_id,
            batch_size=1,
            apply_token="worker-a",
        )
        assert len(row_ids) == 1
        setup_db.execute(
            update(CsvImportBatch)
            .where(CsvImportBatch.tenant_id == "owner")
            .where(CsvImportBatch.id == batch_id)
            .values(
                status="applying",
                apply_token="worker-a",
                locked_until=now_utc() - timedelta(minutes=1),
                updated_at=now_utc() - timedelta(minutes=10),
            )
        )
        setup_db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.id == row_ids[0])
            .values(updated_at=now_utc() - timedelta(minutes=10))
        )
        setup_db.commit()

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 1
        assert applied.remaining_valid_rows == 0

        assert not _refresh_claimed_csv_import_row(
            db,
            tenant_id="owner",
            row_id=row_ids[0],
            apply_token="worker-a",
            now=now_utc(),
        )
        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 1


def test_csv_import_row_idempotency_prevents_duplicate_expense_after_stale_reclaim(
    client: TestClient,
) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="idempotent-row.csv",
            file_obj=_csv_bytes(1),
        )
        public_id = batch.public_id
        batch_id = batch.id
        row_id = setup_db.scalar(
            select(CsvImportRow.id)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
            .limit(1)
        )
        assert row_id is not None
        setup_db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.id == row_id)
            .values(
                status="applying",
                apply_token="worker-a",
                updated_at=now_utc() - timedelta(minutes=10),
            )
        )
        setup_db.add(
            Expense(
                tenant_id="owner",
                amount_cents=100,
                merchant="Merchant 1",
                category="餐饮",
                source="CSV导入",
                status="pending",
                draft_idempotency_key=f"csv-import:{public_id}:2",
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        setup_db.commit()

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.inserted_count == 0
        assert applied.remaining_valid_rows == 0

        expenses = list(
            db.scalars(
                select(Expense)
                .where(Expense.tenant_id == "owner")
                .where(Expense.draft_idempotency_key == f"csv-import:{public_id}:2")
            )
        )
        assert len(expenses) == 1
        row = db.scalar(
            select(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.id == row_id)
        )
        assert row is not None
        assert row.status == "applied"
        assert row.expense_id == expenses[0].id
        assert row.apply_token is None


def test_csv_import_idempotency_conflict_resolver_marks_claimed_row_applied(
    client: TestClient,
) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="idempotent-conflict.csv",
            file_obj=_csv_bytes(1),
        )
        public_id = batch.public_id
        batch_id = batch.id
        row = setup_db.scalar(
            select(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
            .limit(1)
        )
        assert row is not None
        setup_db.execute(
            update(CsvImportBatch)
            .where(CsvImportBatch.tenant_id == "owner")
            .where(CsvImportBatch.id == batch_id)
            .values(
                status="applying",
                apply_token="worker-a",
                locked_until=now_utc() + timedelta(minutes=1),
                last_error="previous failure",
                updated_at=now_utc(),
            )
        )
        setup_db.execute(
            update(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.id == row.id)
            .values(status="applying", apply_token="worker-a", updated_at=now_utc())
        )
        setup_db.add(
            Expense(
                tenant_id="owner",
                amount_cents=100,
                merchant="Merchant 1",
                category="餐饮",
                source="CSV导入",
                status="pending",
                draft_idempotency_key=f"csv-import:{public_id}:2",
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        setup_db.commit()

    with SessionLocal() as db:
        resolved = _resolve_csv_import_idempotency_conflict(
            db,
            tenant_id="owner",
            public_id=public_id,
            row_ids=[row.id],
            apply_token="worker-a",
        )
        assert resolved is not None
        assert resolved.inserted_count == 0
        assert resolved.remaining_valid_rows == 0
        assert resolved.batch.status == "applied"
        assert resolved.batch.last_error is None

        row = db.scalar(
            select(CsvImportRow)
            .where(CsvImportRow.tenant_id == "owner")
            .where(CsvImportRow.batch_id == batch_id)
        )
        assert row is not None
        assert row.status == "applied"
        assert row.expense_id is not None
        assert row.apply_token is None


def test_csv_import_success_clears_previous_apply_error(client: TestClient) -> None:
    del client
    with SessionLocal() as setup_db:
        batch = create_csv_import_batch(
            setup_db,
            tenant_id="owner",
            file_name="clear-last-error.csv",
            file_obj=_csv_bytes(1),
        )
        public_id = batch.public_id
        setup_db.execute(
            update(CsvImportBatch)
            .where(CsvImportBatch.tenant_id == "owner")
            .where(CsvImportBatch.public_id == public_id)
            .values(last_error="previous failure")
        )
        setup_db.commit()

    with SessionLocal() as db:
        applied = apply_csv_import_batch(
            db,
            tenant_id="owner",
            public_id=public_id,
            batch_size=10,
        )
        assert applied.batch.status == "applied"
        assert applied.batch.last_error is None
