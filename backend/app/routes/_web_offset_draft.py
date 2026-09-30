"""Browser-only input metadata and explicit preparation for the existing offset commands."""
from dataclasses import dataclass
from uuid import uuid4

from fastapi import Form, Request
from sqlalchemy import select

from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.routes._web_draft_binding import require_draft_binding, reviewed_draft_scope
from app.schemas import ExpenseFactBundleResponse
from app.services.expense_offset_lifecycle_service import claim_expense_offset_void
from app.services.expense_offset_service import claim_expense_offset_command, expense_fact_bundle


@dataclass(frozen=True)
class OffsetDraft:
    draft_scope: str = ""
    draft_client_ref: str = ""
    original_currency_code: str = ""
    review_latest: bool = False
    review_currency: bool = False


def offset_draft_form(draft_scope: str = Form(default=""), draft_client_ref: str = Form(default=""),
                      original_currency_code: str = Form(default=""), review_latest: str = Form(default=""),
                      review_currency: str = Form(default="")) -> OffsetDraft:
    return OffsetDraft(draft_scope, draft_client_ref, original_currency_code, review_latest == "true", review_currency == "true")


def bind_offset_draft(db, request: Request, selected_id: str, metadata: OffsetDraft) -> str:
    scope = reviewed_draft_scope(db, request, metadata.draft_scope, review=metadata.review_latest)
    require_draft_binding(db, request, ledger_id=selected_id, draft_scope=scope, require_session=False)
    return scope


def prepare_offset_draft(db, *, selected_id, expense_id, draft, metadata, payload, actor_account_id, target_public_id=""):
    # This is the command owner's original claim, rolled back without a financial write.
    # A committed original returns its retained receipt before any new basis is prepared.
    if payload is not None:
        common = {"db": db, "tenant_id": selected_id, "expense_id": expense_id, "payload": payload,
            "actor_account_id": actor_account_id, "idempotency_key": draft["idempotency_key"] or None}
        claimed = (claim_expense_offset_void(**common, offset_public_id=target_public_id) if target_public_id else
            claim_expense_offset_command(**common))
        if isinstance(claimed, ExpenseFactBundleResponse):
            return claimed
    elif db.scalar(select(ApiIdempotencyKey.id).where(ApiIdempotencyKey.tenant_id == selected_id,
            ApiIdempotencyKey.idempotency_key == draft["idempotency_key"])) is not None:
        raise AppError("idempotency_key_reused", "这份原输入无法核实已有编号，请先核对原提交结果。", status_code=409)
    db.rollback()
    current = expense_fact_bundle(db, tenant_id=selected_id, expense_id=expense_id)
    version = current.root.row_version
    if target_public_id:
        target = next((item for item in current.active_offsets if item.public_id == target_public_id), None)
        if target is None:
            raise AppError("expense_offset_not_active", "原撤销对象已不再生效；原输入仍保留，请核实历史。", status_code=409)
        version = target.row_version
    elif metadata.original_currency_code != current.root.original_currency_code and not metadata.review_currency:
        return {**draft, "currency_review": True, "native_result": "review",
            "error": "请核对原金额与当前账单币种，再明确选择。"}
    return {**draft, "expected_row_version": str(version), "idempotency_key": str(uuid4()),
        "draft_client_ref": draft.get("draft_client_ref") or draft["idempotency_key"],
        "original_currency_code": current.root.original_currency_code, "native_result": "prepared"}
