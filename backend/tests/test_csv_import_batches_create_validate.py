from __future__ import annotations

import csv as csv_module
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.errors import AppError
from app.models import CsvImportBatch, CsvImportRow, Expense, LedgerMember
from app.services.csv_import_batch_service import (
    apply_csv_import_batch,
    create_csv_import_batch,
    list_csv_import_rows,
)
from app.services.currency_binding_service import get_capability


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


def test_csv_import_batch_handles_more_than_legacy_preview_limit_with_paged_apply(client: TestClient) -> None:
    del client
    with SessionLocal() as db:
        batch = create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="large.csv",
            file_obj=_csv_bytes(10_000),
        )
        assert batch.total_rows == 10_000
        assert batch.valid_rows == 10_000
        assert batch.error_rows == 0

        second_page = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=2,
            page_size=500,
        )
        assert second_page.total == 10_000
        assert len(second_page.items) == 500
        assert second_page.items[0].line_number == 502

        last_page = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=20,
            page_size=500,
        )
        assert len(last_page.items) == 500
        assert last_page.items[0].line_number == 9502

        inserted_count = 0
        for expected_remaining in range(9000, -1, -1000):
            applied = apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=batch.public_id,
                batch_size=1000,
            )
            inserted_count += applied.inserted_count
            assert applied.inserted_count == 1000
            assert applied.remaining_valid_rows == expected_remaining
        assert inserted_count == 10_000
        assert applied.batch.status == "applied"

        with pytest.raises(AppError) as terminal_apply:
            apply_csv_import_batch(
                db,
                tenant_id="owner",
                public_id=batch.public_id,
                batch_size=700,
            )
        assert terminal_apply.value.status_code == 409

        inserted = db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.tenant_id == "owner")
            .where(Expense.source == "CSV导入")
        )
        assert inserted == 10_000


@pytest.mark.currency_binding_unbound
def test_csv_import_batch_create_inserts_rows_in_chunks(
    identity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del identity
    import app.services.csv_import_batch_service._lifecycle as lifecycle_mod

    monkeypatch.setattr(lifecycle_mod, "CREATE_BATCH_INSERT_CHUNK_SIZE", 2)
    with SessionLocal() as db:
        empty_batch = create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="header-only.csv",
            file_obj=_csv_bytes(0),
        )
        assert empty_batch.total_rows == 0
        assert get_capability(db).state == "EMPTY"

    real_row_from_parsed = lifecycle_mod._row_from_parsed
    built_rows = 0

    def fail_in_second_chunk(*args, **kwargs):
        nonlocal built_rows
        built_rows += 1
        if built_rows == 3:
            raise SQLAlchemyError("injected second-chunk failure")
        return real_row_from_parsed(*args, **kwargs)

    monkeypatch.setattr(lifecycle_mod, "_row_from_parsed", fail_in_second_chunk)
    with SessionLocal() as db, pytest.raises(SQLAlchemyError):
        create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="rolled-back.csv",
            file_obj=_csv_bytes(5),
        )
    with SessionLocal() as db:
        assert get_capability(db).state == "EMPTY"
        assert db.scalar(select(func.count()).select_from(CsvImportRow)) == 0
        assert db.scalar(select(func.count()).select_from(CsvImportBatch)) == 1

    monkeypatch.setattr(lifecycle_mod, "_row_from_parsed", real_row_from_parsed)
    with SessionLocal() as db:
        real_commit = db.commit
        real_flush = db.flush
        commit_count = 0
        flush_count = 0

        def counted_commit() -> None:
            nonlocal commit_count
            commit_count += 1
            real_commit()

        def counted_flush(*args, **kwargs) -> None:
            nonlocal flush_count
            flush_count += 1
            real_flush(*args, **kwargs)

        monkeypatch.setattr(db, "commit", counted_commit)
        monkeypatch.setattr(db, "flush", counted_flush)
        batch = create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="chunked-create.csv",
            file_obj=_csv_bytes(5),
        )

        assert batch.total_rows == 5
        assert flush_count >= 4
        assert commit_count == 1
        assert get_capability(db).state == "ACTIVE"

        rows = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=1,
            page_size=10,
        )
        assert rows.total == 5


def test_csv_import_tags_are_normalized_before_batch_storage(identity) -> None:
    del identity
    csv = "amount_yuan,merchant,tags\n1.00,Tagged Cafe,\" food , Food, 家庭 \"\n"
    with SessionLocal() as db:
        batch = create_csv_import_batch(
            db,
            tenant_id="owner",
            file_name="tags.csv",
            file_obj=BytesIO(csv.encode("utf-8")),
        )
        rows = list_csv_import_rows(
            db,
            tenant_id="owner",
            public_id=batch.public_id,
            page=1,
            page_size=10,
        )
        assert rows.items[0].tags == "food, 家庭"


def test_csv_import_batch_converts_csv_reader_errors_to_invalid_request(client: TestClient) -> None:
    del client
    old_limit = csv_module.field_size_limit()
    csv_module.field_size_limit(8)
    try:
        with SessionLocal() as db, pytest.raises(AppError) as exc_info:
            create_csv_import_batch(
                db,
                tenant_id="owner",
                file_name="bad.csv",
                file_obj=BytesIO(b"amount_yuan,merchant\n1.00,VeryLongMerchant\n"),
            )
    finally:
        csv_module.field_size_limit(old_limit)
    assert exc_info.value.error == "invalid_request"


def test_csv_import_rejects_conflicting_amount_yuan_and_cents(client: TestClient, *, identity) -> None:
    csv = "amount_yuan,amount_cents,merchant\n2.00,100,Conflicting Cafe\n"
    created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("conflict.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["valid_rows"] == 0
    assert batch["error_rows"] == 1

    rows = client.get(
        f"/api/imports/csv/{batch['public_id']}/rows?status=error",
        headers=identity.app_headers,
    )
    assert rows.status_code == 200, rows.json()
    assert rows.json()["items"][0]["status"] == "error"
    assert "amount_yuan" in rows.json()["items"][0]["error_message"]
    assert "amount_cents" in rows.json()["items"][0]["error_message"]


def test_csv_import_foreign_amount_cents_is_original_minor_not_home_amount(client: TestClient, *, identity) -> None:
    rate = client.put(
        "/api/exchange-rates/USD/2026-05-04",
        headers=identity.app_headers,
        json={
            "currency_code": "USD",
            "rate_date": "2026-05-04",
            "rate_to_cny": "7.0000",
            "source": "manual",
        },
    )
    assert rate.status_code == 200, rate.json()
    csv = "\n".join(
        [
            "amount_cents,original_currency_code,exchange_rate_to_cny,exchange_rate_date,merchant,category",
            "12345,USD,7.0000,2026-05-04,Foreign Cafe,餐饮",
            "",
        ]
    )
    created = client.post(
        "/api/imports/csv",
        headers=identity.app_headers,
        files={"csv_file": ("foreign.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert created.status_code == 201, created.json()
    batch = created.json()
    assert batch["valid_rows"] == 1
    assert batch["error_rows"] == 0

    rows = client.get(
        f"/api/imports/csv/{batch['public_id']}/rows",
        headers=identity.app_headers,
    )
    assert rows.status_code == 200, rows.json()
    row = rows.json()["items"][0]
    assert row["amount_cents"] is None
    assert row["original_currency_code"] == "USD"
    assert row["original_amount_minor"] == 12345

    applied = client.post(
        f"/api/imports/csv/{batch['public_id']}/apply",
        headers=identity.app_headers,
        json={"batch_size": 10},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["inserted_count"] == 1

    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200, pending.json()
    target = next(item for item in pending.json() if item["merchant"] == "Foreign Cafe")
    assert target["original_currency_code"] == "USD"
    assert target["original_amount_minor"] == 12345
    assert target["exchange_rate_date"] == "2026-05-04"
    assert target["amount_cents"] == 86415
