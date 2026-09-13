"""Read the original manual acceptance for command replay, Web ACK and local OCC."""

from hashlib import sha256

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.schemas import ExpenseManualCreateRequest, ExpenseResponse
from app.services.idempotency import fingerprint_request


def local_ref_storage_key(device_id: int, client_ref: str) -> str:
    """The ``Expense.draft_idempotency_key`` value for a device-local manual create.

    Single source of truth for the ``{device_id}:{client_ref}`` composite so the
    create side (which STORES it — ``create_manual_expense``) and the resolve side
    (which looks it up — ``resolve_expense``) can never drift. A drift would make a
    ``local:{client_ref}`` mutation silently miss its row.
    """
    return f"{device_id}:{client_ref}"


def _manual_request_fingerprint(payload: ExpenseManualCreateRequest) -> str:
    """sha256 of the user-supplied manual-create body (issue #65 slice 1).

    Computed from the REQUEST as sent — never from the stored row — so the server's
    own mutations (auto-classify of ``category``, the ``expense_time`` → ``now``
    default, FX rate-derived ``amount_cents``) can't make a faithful replay look like
    a different request. ``client_ref`` is excluded: it IS the key, not part of the
    intent it guards.
    """
    body = payload.model_dump(mode="json", exclude_unset=True, exclude={"client_ref"})
    return fingerprint_request(
        operation="create_manual_expense",
        target_id=None,
        body=body,
        expected_row_version=None,
    )


def _manual_receipt_key(device_id: int, client_ref: str) -> str:
    # The original Expense locator remains unchanged; its maximum length exceeds
    # the shared API key column. Namespace and hash only this storage index.
    key = local_ref_storage_key(device_id, client_ref)
    return sha256(f"create_manual_expense:{key}".encode()).hexdigest()


def _manual_review_error(expense_id: int | None = None) -> AppError:
    return AppError("manual_create_original_requires_review", status_code=409,
        details={"expense_id": expense_id} if expense_id is not None else None)


def _manual_receipt(row: ApiIdempotencyKey) -> ExpenseResponse:
    try:
        receipt = ExpenseResponse.model_validate(row.response_body)
        if (row.operation != "create_manual_expense" or row.resource_type != "expense"
                or str(receipt.id) != row.resource_id or receipt.id < 1 or receipt.row_version < 1
                or receipt.source != "手动记账" or receipt.status not in {"pending", "confirmed"}):
            raise ValueError("Original manual receipt does not match its resource")
        return receipt
    except (ValidationError, ValueError) as exc:
        resource_id = row.resource_id or ""
        raise _manual_review_error(int(resource_id) if resource_id.isdecimal() else None) from exc


def read_manual_creation_receipt(
    db: Session, *, tenant_id: str, device_id: int, client_ref: str,
) -> ExpenseResponse | None:
    """Read the same command receipt for a bound Web acknowledgement; never infer one."""
    row = db.scalar(select(ApiIdempotencyKey).where(
        ApiIdempotencyKey.tenant_id == tenant_id,
        ApiIdempotencyKey.idempotency_key == _manual_receipt_key(device_id, client_ref),
        ApiIdempotencyKey.status == "succeeded",
    ))
    if row is None:
        return None
    try:
        return _manual_receipt(row)
    except AppError:
        return None
