"""Shared helpers for test_database_migration_*.py.

These were extracted from the original 1297L monolith so the per-entity test
files (baseline / family_role / tenant_integrity / expense / recurring / ...)
can share schema-probing and legacy-row-insertion primitives without
duplicating them.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from app.models import Expense


def reset_empty_database() -> None:
    from app.database import Base
    Base.metadata.drop_all(bind=engine)


def expense_columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("expenses")}


def table_columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def indexes(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def create_v01_expenses_table() -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS expenses"))
        connection.execute(
            text(
                """
                CREATE TABLE expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount_cents INTEGER,
                    merchant VARCHAR(255),
                    category VARCHAR(64) NOT NULL DEFAULT '其他',
                    note TEXT,
                    source VARCHAR(64) NOT NULL DEFAULT 'iPhone截图',
                    image_path VARCHAR(500),
                    image_hash VARCHAR(128),
                    raw_text TEXT,
                    confidence FLOAT,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    expense_time DATETIME,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    confirmed_at DATETIME,
                    rejected_at DATETIME
                )
                """
            )
        )


def table_create_sql(table_name: str) -> str:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
            {"name": table_name},
        ).one()
    return str(row[0])


def insert_legacy_expense(
    *,
    amount_cents: int | None = None,
    merchant: str | None = "老商家",
    category: str = "吃饭",
    status: str = "pending",
    image_path: str | None = None,
    thumbnail_path: str | None = None,
    tenant_id: str | None = None,
    public_id: str | None = None,
    tags: str | None = None,
) -> int:
    columns = expense_columns()
    values = {
        "amount_cents": amount_cents,
        "merchant": merchant,
        "category": category,
        "note": "旧备注",
        "source": "iPhone截图",
        "image_path": image_path,
        "image_hash": "legacy-hash",
        "raw_text": "",
        "confidence": None,
        "status": status,
        "expense_time": "2026-05-04 08:00:00",
        "created_at": "2026-05-04 08:00:00",
        "updated_at": "2026-05-04 08:00:00",
        "confirmed_at": "2026-05-04 08:10:00" if status == "confirmed" else None,
        "rejected_at": None,
    }
    if "thumbnail_path" in columns:
        values["thumbnail_path"] = thumbnail_path
    if "tenant_id" in columns and tenant_id is not None:
        values["tenant_id"] = tenant_id
    if "public_id" in columns:
        values["public_id"] = public_id
    if "tags" in columns:
        values["tags"] = tags

    keys = [key for key in values if key in columns]
    placeholders = ", ".join(f":{key}" for key in keys)
    sql = f"INSERT INTO expenses ({', '.join(keys)}) VALUES ({placeholders})"
    with engine.begin() as connection:
        result = connection.execute(text(sql), {key: values[key] for key in keys})
        return int(result.lastrowid)


def fetch_expense(expense_id: int) -> dict[str, object]:
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT * FROM expenses WHERE id = :id"),
            {"id": expense_id},
        ).mappings().one()
    return dict(row)


def insert_cross_ledger_duplicate_metadata() -> tuple[int, int]:
    with SessionLocal() as db:
        owner = Expense(
            tenant_id="owner",
            amount_cents=1000,
            merchant="owner-duplicate-source",
            category="鍏朵粬",
            status="pending",
        )
        tester = Expense(
            tenant_id="tester_1",
            amount_cents=1000,
            merchant="tester-duplicate-target",
            category="鍏朵粬",
            status="pending",
        )
        db.add_all([owner, tester])
        db.commit()
        owner_id = owner.id
        tester_id = tester.id

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            text(
                "UPDATE expenses "
                "SET duplicate_status = 'suspected', "
                "duplicate_of_id = :target_id, "
                "duplicate_reason = 'cross-ledger dirty row' "
                "WHERE id = :expense_id"
            ),
            {"expense_id": owner_id, "target_id": tester_id},
        )
        connection.execute(
            text(
                "INSERT INTO duplicate_ignores "
                "(tenant_id, expense_id, duplicate_of_id, kind, created_at) "
                "VALUES ('owner', :expense_id, :target_id, 'similar', '2026-05-04 08:00:00')"
            ),
            {"expense_id": owner_id, "target_id": tester_id},
        )
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    return owner_id, tester_id
