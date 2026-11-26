"""Retained original references shared by export and orphan maintenance."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app import models as m
from app.services.attachment_cleanup_service import pending_cleanup_references
from app.services.file_service import resolve_upload_path_for_tenant, upload_reference_for_path


@dataclass(frozen=True, slots=True)
class RetainedOriginalCheck:
    tenant_id: str
    relative_path: str
    expected_sha256: str | None
    expected_size_bytes: int | None
    require_digest: bool
    source_kind: str


def original_receipt_references_query(receipt_query: Select, *, tenant_id: str) -> Select:
    """Keep accepted original identity separate from the current attachment.

    Callers authorize their own entrance. This projection admits only retained,
    successful original-bearing receipts within the requested ledger; private
    command bodies and storage paths are never a public response from this owner.
    """
    receipt = receipt_query.order_by(None).subquery("accepted_original_receipts")
    body = case((receipt.c.resource_type == "expense_offset", receipt.c.response_body["root"]),
        else_=receipt.c.response_body)
    original_operations = ("attach_original", "verify_original", "replenish_original",
        "retry_original_cleanup", "cancel_original_cleanup")
    original_command = and_(receipt.c.resource_type == "expense",
        body["operation"].as_string().in_(original_operations),
        body["sha256"].as_string().is_not(None))
    upload_receipt = receipt.c.resource_type == "upload_receipt"
    producer_receipt = or_(upload_receipt, original_command)
    expense_id = case((original_command, body["expense_id"].as_integer()),
        else_=body["id"].as_integer())
    expense_public_id = body["public_id"].as_string()
    image_hash = case((original_command, body["sha256"].as_string()),
        else_=body["image_hash"].as_string())
    # Digest-only receipts can use today's reference only for the same bytes.
    image_path = case((and_(producer_receipt, image_hash == m.Expense.image_hash), m.Expense.image_path),
        (producer_receipt, None), else_=body["image_path"].as_string())
    image_deleted_at = body["image_deleted_at"].as_string()
    historical_image_cleaned = func.max(case((image_deleted_at.is_not(None), 1), else_=0)).over(
        partition_by=(expense_id, expense_public_id, image_path))
    return select(
        receipt.c.id.label("accepted_operation_id"), receipt.c.completed_at.label("accepted_at"),
        expense_id.label("expense_id"), expense_public_id.label("expense_public_id"),
        image_path.label("image_path"), image_hash.label("image_hash"),
        image_deleted_at.label("image_deleted_at"), historical_image_cleaned.label("historical_image_cleaned"),
        body["thumbnail_path"].as_string().label("thumbnail_path"),
        body["thumbnail_deleted_at"].as_string().label("thumbnail_deleted_at"),
        m.Expense.image_path.label("current_image_path"), m.Expense.thumbnail_path.label("current_thumbnail_path"),
        m.Expense.image_deleted_at.label("current_image_deleted_at"),
        m.Expense.thumbnail_deleted_at.label("current_thumbnail_deleted_at"),
        m.Expense.attachment_cleanup_request, m.Expense.image_replenished_at,
    ).select_from(receipt).outerjoin(m.Expense, and_(m.Expense.tenant_id == tenant_id,
        m.Expense.id == expense_id, m.Expense.public_id == expense_public_id)).where(
            receipt.c.tenant_id == tenant_id,
            receipt.c.status == "succeeded",
            receipt.c.resource_type.in_(("expense", "expense_offset", "upload_receipt")),
            expense_id.is_not(None),
        ).order_by(receipt.c.id)


def historical_original_is_cleaned(row: Mapping[str, object]) -> bool:
    """Use explicit cleanup evidence, never mere replacement or disappearance."""
    if row.get("image_deleted_at") is not None or row.get("historical_image_cleaned"):
        return True
    source = row.get("image_path")
    if source and source == row.get("current_image_path") and row.get("current_image_deleted_at") is not None:
        return True
    cleanup = row.get("attachment_cleanup_request")
    image = cleanup.get("image") if isinstance(cleanup, dict) else None
    return isinstance(image, dict) and image.get("reference") == source and image.get("outcome") == "deleted"


def _relative_upload_path(path: Path) -> str | None:
    try:
        return upload_reference_for_path(path)
    except RuntimeError:
        return None


def _normalize_upload_reference(relative_path: str | None, tenant_id: str) -> str | None:
    if not relative_path:
        return None
    candidate = resolve_upload_path_for_tenant(relative_path, tenant_id)
    if candidate is None:
        return None
    return _relative_upload_path(candidate)


def _require_normalized_upload_reference(
    relative_path: str | None,
    tenant_id: str,
    *,
    source_kind: str,
) -> str:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError(f"invalid retained original reference ({source_kind})")
    normalized = _normalize_upload_reference(relative_path, tenant_id)
    if normalized is None:
        raise ValueError(f"invalid retained original reference ({source_kind})")
    return normalized


def _build_retained_check(
    *,
    tenant_id: str,
    relative_path: str | None,
    source_kind: str,
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    require_digest: bool = False,
) -> RetainedOriginalCheck:
    normalized = _require_normalized_upload_reference(
        relative_path, tenant_id, source_kind=source_kind,
    )
    return RetainedOriginalCheck(
        tenant_id=tenant_id,
        relative_path=normalized,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
        require_digest=require_digest,
        source_kind=source_kind,
    )


def _iter_expense_original_checks(db: Session, tenant_id: str) -> list[RetainedOriginalCheck]:
    checks: list[RetainedOriginalCheck] = []
    expense_rows = db.execute(
        select(
            m.Expense.image_path,
            m.Expense.image_hash,
            m.Expense.thumbnail_path,
            m.Expense.image_deleted_at,
            m.Expense.thumbnail_deleted_at,
            m.Expense.attachment_cleanup_request,
        )
        .where(m.Expense.tenant_id == tenant_id)
        .where(
            or_(
                and_(m.Expense.image_path.is_not(None), m.Expense.image_deleted_at.is_(None)),
                and_(m.Expense.thumbnail_path.is_not(None), m.Expense.thumbnail_deleted_at.is_(None)),
                m.Expense.attachment_cleanup_request.is_not(None),
            )
        )
    )
    for image_path, image_hash, thumbnail_path, image_deleted_at, thumbnail_deleted_at, cleanup_request in expense_rows:
        if image_path is not None and image_deleted_at is None:
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=image_path,
                    source_kind="expense_image",
                    expected_sha256=image_hash,
                )
            )
        if thumbnail_path is not None and thumbnail_deleted_at is None:
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=thumbnail_path,
                    source_kind="expense_thumbnail",
                )
            )
        for reference in pending_cleanup_references(cleanup_request):
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=reference,
                    source_kind="expense_pending_cleanup",
                    expected_sha256=image_hash if reference == image_path else None,
                )
            )
    return checks


def _iter_debt_capture_original_checks(db: Session, tenant_id: str) -> list[RetainedOriginalCheck]:
    checks: list[RetainedOriginalCheck] = []
    capture_rows = db.execute(
        select(
            m.DebtBillCapture.image_path,
            m.DebtBillCapture.image_hash,
            m.DebtBillCapture.image_size_bytes,
            m.DebtBillCapture.image_deleted_at,
            m.DebtBillCapture.attachment_cleanup_request,
        ).where(m.DebtBillCapture.tenant_id == tenant_id)
    )
    for image_path, image_hash, image_size_bytes, deleted_at, cleanup_request in capture_rows:
        if deleted_at is None:
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=image_path,
                    source_kind="debt_bill_capture",
                    expected_sha256=image_hash,
                    expected_size_bytes=image_size_bytes,
                    require_digest=True,
                )
            )
        for reference in pending_cleanup_references(cleanup_request):
            matches_primary = reference == image_path
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=reference,
                    source_kind="debt_bill_capture_pending_cleanup",
                    expected_sha256=image_hash if matches_primary else None,
                    expected_size_bytes=image_size_bytes if matches_primary else None,
                    require_digest=matches_primary,
                )
            )
    return checks


def _iter_historical_original_checks(db: Session, tenant_id: str) -> list[RetainedOriginalCheck]:
    checks: list[RetainedOriginalCheck] = []
    history = original_receipt_references_query(select(m.ApiIdempotencyKey), tenant_id=tenant_id)
    for original in db.execute(history).mappings():
        if historical_original_is_cleaned(original):
            continue
        hist_image = original["image_path"]
        if hist_image is not None:
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=hist_image,
                    source_kind="historical_original",
                    expected_sha256=original["image_hash"],
                )
            )
        hist_thumb = original["thumbnail_path"]
        if hist_thumb is not None and original["thumbnail_deleted_at"] is None:
            checks.append(
                _build_retained_check(
                    tenant_id=tenant_id,
                    relative_path=hist_thumb,
                    source_kind="historical_thumbnail",
                )
            )
    return checks


def iter_retained_original_checks(db: Session, tenant_id: str) -> list[RetainedOriginalCheck]:
    return [
        *_iter_expense_original_checks(db, tenant_id),
        *_iter_debt_capture_original_checks(db, tenant_id),
        *_iter_historical_original_checks(db, tenant_id),
    ]


def referenced_upload_paths(db: Session, tenant_id: str) -> set[str]:
    rows = db.execute(
        select(
            m.Expense.image_path,
            m.Expense.thumbnail_path,
            m.Expense.image_deleted_at,
            m.Expense.thumbnail_deleted_at,
            m.Expense.attachment_cleanup_request,
        )
        .where(m.Expense.tenant_id == tenant_id)
        .where(
            or_(
                and_(m.Expense.image_path.is_not(None), m.Expense.image_deleted_at.is_(None)),
                and_(m.Expense.thumbnail_path.is_not(None), m.Expense.thumbnail_deleted_at.is_(None)),
                m.Expense.attachment_cleanup_request.is_not(None),
            )
        )
    )
    referenced: set[str] = set()
    for image_path, thumbnail_path, image_deleted_at, thumbnail_deleted_at, cleanup_request in rows:
        if image_deleted_at is None:
            normalized_image = _normalize_upload_reference(image_path, tenant_id)
            if normalized_image:
                referenced.add(normalized_image)
        if thumbnail_deleted_at is None:
            normalized_thumbnail = _normalize_upload_reference(thumbnail_path, tenant_id)
            if normalized_thumbnail:
                referenced.add(normalized_thumbnail)
        for reference in pending_cleanup_references(cleanup_request):
            normalized = _normalize_upload_reference(reference, tenant_id)
            if normalized:
                referenced.add(normalized)
    history = original_receipt_references_query(select(m.ApiIdempotencyKey), tenant_id=tenant_id)
    sources = db.execute(select(m.DebtBillCapture.image_path, m.DebtBillCapture.image_deleted_at,
        m.DebtBillCapture.attachment_cleanup_request).where(m.DebtBillCapture.tenant_id == tenant_id))
    for image_path, deleted_at, cleanup_request in sources:
        references = pending_cleanup_references(cleanup_request)
        if deleted_at is None:
            references = (*references, image_path)
        for reference in references:
            normalized = _normalize_upload_reference(reference, tenant_id)
            if normalized:
                referenced.add(normalized)
    for original in db.execute(history).mappings():
        if historical_original_is_cleaned(original):
            continue
        normalized = _normalize_upload_reference(original["image_path"], tenant_id)
        if normalized:
            referenced.add(normalized)
    return referenced
