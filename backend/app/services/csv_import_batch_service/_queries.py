"""Read-only CsvImportBatch lookups shared across _lifecycle / _csv_io /
_apply / _apply_lease / _idempotency.

Pulled out of _lifecycle to break the _csv_io ↔ _lifecycle import
cycle (5 lazy ``from ._lifecycle import get_csv_import_batch`` sites).
Pure DB query, no side effects — safe for any sibling to import at
module load.

Re-exported from ``_lifecycle`` so external callers
(``from app.services.csv_import_batch_service._lifecycle import
get_csv_import_batch``) keep working.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import AppError
from app.ledger_scope import ledger_scoped_select
from app.models import CsvImportBatch

__all__ = ["get_csv_import_batch"]


def get_csv_import_batch(
    db: Session, *, tenant_id: str, public_id: str
) -> CsvImportBatch:
    batch = db.scalar(
        ledger_scoped_select(CsvImportBatch, tenant_id).where(
            CsvImportBatch.public_id == public_id
        )
    )
    if batch is None:
        raise AppError("import_batch_not_found", "导入批次不存在。", status_code=404)
    return batch
