"""PostgreSQL facts for one complete-dataset backup snapshot."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Expense


def begin_dataset_backup_snapshot(db: Session) -> str:
    try:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE, READ ONLY, DEFERRABLE"))
        snapshot = db.scalar(text("SELECT pg_export_snapshot()"))
    except SQLAlchemyError as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not isinstance(snapshot, str) or not snapshot or any(character in snapshot for character in "\x00\r\n"):
        raise AppError("backup_incomplete", status_code=500)
    return snapshot


def assert_dataset_writers_drained(db: Session) -> None:
    others = db.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND backend_type = 'client backend' "
            "AND pid <> pg_backend_pid()"
        )
    )
    if others != 0:
        raise AppError("backup_incomplete", status_code=409)


def assert_dataset_database_binding(db: Session, database_url: str) -> None:
    try:
        expected = make_url(database_url).database
    except (ArgumentError, TypeError, ValueError) as exc:
        raise AppError("backup_incomplete", status_code=500) from exc
    if not expected or db.scalar(text("SELECT current_database()")) != expected:
        raise AppError("backup_incomplete", status_code=500)


def read_original_reference_rows(db: Session) -> tuple[tuple[str, str, str | None], ...]:
    rows = db.execute(
        select(Expense.tenant_id, Expense.image_path, Expense.image_hash)
        .where(Expense.image_path.is_not(None))
        .where(Expense.image_deleted_at.is_(None))
        .order_by(Expense.tenant_id, Expense.image_path)
    ).all()
    return tuple(
        (
            str(row.tenant_id),
            str(row.image_path),
            None if row.image_hash is None else str(row.image_hash),
        )
        for row in rows
    )


__all__ = [
    "assert_dataset_database_binding",
    "assert_dataset_writers_drained",
    "begin_dataset_backup_snapshot",
    "read_original_reference_rows",
]
