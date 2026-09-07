"""Read the persisted aggregate behind an upload's original receipt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiIdempotencyKey, BackgroundTask, Expense
from app.services.idempotency import IDEMPOTENCY_STATUS_SUCCEEDED
from app.services.pending_enrichment_task_service import PENDING_EXPENSE_ENRICHMENT_TASK_TYPE

if TYPE_CHECKING:
    from app.schemas import UploadResponse
    from app.services.background_task_service import PreparedBackgroundTask


def upload_commit_is_durable(
    db: Session,
    claim_id: int,
    receipt: UploadResponse,
    prepared_task: PreparedBackgroundTask,
) -> bool:
    stored_receipt = db.scalar(
        select(ApiIdempotencyKey.response_body)
        .join(Expense, Expense.public_id == ApiIdempotencyKey.resource_id)
        .join(BackgroundTask, BackgroundTask.id == prepared_task.task_id)
        .where(
            ApiIdempotencyKey.id == claim_id,
            ApiIdempotencyKey.tenant_id == prepared_task.payload["tenant_id"],
            ApiIdempotencyKey.operation == "upload_screenshot",
            ApiIdempotencyKey.status == IDEMPOTENCY_STATUS_SUCCEEDED,
            ApiIdempotencyKey.resource_type == "upload_receipt",
            Expense.id == receipt.id,
            Expense.public_id == receipt.public_id,
            Expense.tenant_id == ApiIdempotencyKey.tenant_id,
            BackgroundTask.public_id == prepared_task.task_public_id,
            BackgroundTask.public_id == receipt.enrichment_task_public_id,
            BackgroundTask.tenant_id == ApiIdempotencyKey.tenant_id,
            BackgroundTask.task_type == PENDING_EXPENSE_ENRICHMENT_TASK_TYPE,
        )
    )
    return stored_receipt == receipt.model_dump(mode="json")
