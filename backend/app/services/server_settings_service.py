from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, get_settings
from app.models import Expense
from app.services.time_service import to_iso
from app.tenants import DEFAULT_TENANT_ID


def _upload_storage_bytes(db: Session, tenant_id: str) -> int:
    settings = get_settings()
    tenant_upload_dir = (settings.upload_dir / tenant_id).resolve()
    total = 0
    rows = db.execute(
        select(Expense.image_path, Expense.thumbnail_path)
        .where(Expense.tenant_id == tenant_id)
        .where((Expense.image_path.is_not(None)) | (Expense.thumbnail_path.is_not(None)))
    )
    for image_path, thumbnail_path in rows:
        for relative_path in {image_path, thumbnail_path}:
            if not relative_path:
                continue
            candidate = (BACKEND_ROOT / relative_path).resolve()
            try:
                candidate.relative_to(settings.upload_dir)
                candidate.relative_to(tenant_upload_dir)
            except ValueError:
                continue
            if candidate.is_file():
                total += candidate.stat().st_size
    return total


def _count_expenses(db: Session, *, tenant_id: str, status: str | None = None, duplicate_status: str | None = None) -> int:
    statement = select(func.count()).select_from(Expense).where(Expense.tenant_id == tenant_id)
    if status is not None:
        statement = statement.where(Expense.status == status)
    if duplicate_status is not None:
        statement = statement.where(Expense.duplicate_status == duplicate_status)
    return int(db.scalar(statement) or 0)


def server_settings_snapshot(
    db: Session,
    *,
    ledger_id: str,
    account_name: str,
    ledger_name: str,
    device_name: str,
    role: str,
) -> dict[str, int | bool | str | float | None]:
    latest_upload_at = db.scalar(select(func.max(Expense.created_at)).where(Expense.tenant_id == ledger_id))
    storage_bytes = _upload_storage_bytes(db, ledger_id)
    return {
        "account_name": account_name,
        "ledger_id": ledger_id,
        "ledger_name": ledger_name,
        "ledger_is_default": ledger_id == DEFAULT_TENANT_ID,
        "device_name": device_name,
        "role": role,
        "status": "ok",
        "storage_status": "normal",
        "pending_count": _count_expenses(db, tenant_id=ledger_id, status="pending"),
        "confirmed_count": _count_expenses(db, tenant_id=ledger_id, status="confirmed"),
        "rejected_count": _count_expenses(db, tenant_id=ledger_id, status="rejected"),
        "suspected_duplicate_count": _count_expenses(db, tenant_id=ledger_id, duplicate_status="suspected"),
        "upload_storage_bytes": storage_bytes,
        "latest_upload_at": to_iso(latest_upload_at),
    }
