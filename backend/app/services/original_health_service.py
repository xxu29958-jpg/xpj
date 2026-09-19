"""Read-only, per-bill original observations; thumbnails are separate evidence."""

from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas._original_attachment import OriginalHealthResponse
from app.services.expense_query import get_expense
from app.services.original_read_service import read_original_snapshot, recorded_original_digest
from app.services.time_service import now_utc


def inspect_expense_original(db: Session, *, expense_id: int, tenant_id: str) -> OriginalHealthResponse:
    expense = get_expense(db, expense_id, tenant_id)
    result = OriginalHealthResponse(expense_id=expense.id, public_id=expense.public_id,
        row_version=expense.row_version, state="none", checked_at=now_utc(),
        expected_sha256=recorded_original_digest(expense.image_hash))
    if expense.image_deleted_at is not None:
        return result.model_copy(update={"state": "cleaned"})
    if not expense.image_path and not expense.image_hash:
        return result
    try:
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=tenant_id,
                                    expected_sha256=expense.image_hash) as snapshot:
            return result.model_copy(update={"state": "verified" if snapshot.verified else "unverified",
                "observed_sha256": snapshot.sha256, "size_bytes": snapshot.size_bytes,
                "media_type": snapshot.media_type, "checked_at": now_utc()})
    except AppError as exc:
        states = {"image_not_found": "missing", "image_integrity_mismatch": "corrupt",
                  "image_read_failed": "unreadable"}
        if exc.error not in states:
            raise
        return result.model_copy(update={"state": states[exc.error], "checked_at": now_utc()})
