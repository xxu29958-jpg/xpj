"""Retained original references shared by export and orphan maintenance."""

from collections.abc import Mapping

from sqlalchemy import Select, and_, case, func, or_, select

from app import models as m


def original_receipt_references_query(receipt_query: Select, *, tenant_id: str) -> Select:
    """Keep accepted original identity separate from the current attachment.

    Callers authorize their own entrance. This projection admits only retained,
    successful original-bearing receipts within the requested ledger; private
    command bodies and storage paths are never a public response from this owner.
    """
    receipt = receipt_query.order_by(None).subquery("accepted_original_receipts")
    body = case((receipt.c.resource_type == "expense_offset", receipt.c.response_body["root"]),
        else_=receipt.c.response_body)
    original_operations = ("verify_original", "replenish_original",
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
