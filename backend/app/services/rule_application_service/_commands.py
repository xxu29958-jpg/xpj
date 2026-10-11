"""Original apply commands and their first results share the financial transaction."""

from typing import Literal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.schemas import RuleApplyConfirmedResponse, RuleApplyPendingResponse
from app.services.idempotency import (
    IdempotencyOutcomeKind,
    claim_idempotency_key,
    fingerprint_request,
    mark_idempotency_succeeded,
)
from app.services.rule_application_service._apply import apply_rules_to_confirmed, apply_rules_to_pending
from app.services.rule_application_service._preview import validate_rule_application_preview


def apply_rules_idempotently(db: Session, *, tenant_id: str, status: Literal["pending", "confirmed"],
    preview_token: str | None, idempotency_key: str | None, max_scan: int = 500,
    actor_account_id: int | None = None, actor_device_id: int | None = None,
) -> RuleApplyPendingResponse | RuleApplyConfirmedResponse:
    if not idempotency_key:
        raise AppError("idempotency_key_required", status_code=422)
    if len(idempotency_key) > 64:
        raise AppError("invalid_request", status_code=422)
    operation = f"apply_{status}_rules"
    claim = claim_idempotency_key(db, tenant_id=tenant_id, idempotency_key=idempotency_key,
        operation=operation, target_type="rule_application_batch", target_id=None,
        request_fingerprint=fingerprint_request(operation=operation, target_id=None,
            body={"confirm": True, "preview_token": preview_token, "max_scan": max_scan}, expected_row_version=None))
    if claim.kind is IdempotencyOutcomeKind.IN_PROGRESS:
        raise AppError("idempotency_key_in_progress", status_code=409)
    if claim.kind is IdempotencyOutcomeKind.FINGERPRINT_MISMATCH:
        raise AppError("idempotency_key_reused", status_code=422)
    response_type = RuleApplyConfirmedResponse if status == "confirmed" else RuleApplyPendingResponse
    if claim.kind is IdempotencyOutcomeKind.HIT:
        try:
            receipt = response_type.model_validate(claim.row.response_body)
            if (receipt.command_key != idempotency_key or receipt.application_public_id != claim.row.resource_id
                or bool(receipt.changed_count) != bool(receipt.application_public_id)
                or isinstance(receipt, RuleApplyConfirmedResponse) and receipt.dry_run):
                raise ValueError("Original result does not match the accepted command")
            return receipt
        except (ValueError, ValidationError) as exc:
            raise AppError("rule_original_requires_review", "原应用已被接受，但原结果无法核对。请查看应用记录。", status_code=409) from exc
    preview = validate_rule_application_preview(db, tenant_id=tenant_id, status=status,
        preview_token=preview_token, max_scan=max_scan)
    apply = apply_rules_to_confirmed if status == "confirmed" else apply_rules_to_pending
    scanned, changed, limited, public_id = apply(db, tenant_id=tenant_id, preview_token=preview_token,
        max_scan=max_scan, actor_account_id=actor_account_id, actor_device_id=actor_device_id, commit=False)
    fields = {"command_key": idempotency_key, "application_public_id": public_id,
        "changed_count": changed, "unavailable_count": preview["unavailable_count"],
        "missing_currency_codes": preview["missing_currency_codes"], "scan_limit_reached": limited, "scan_limit": max_scan}
    receipt = (RuleApplyConfirmedResponse(dry_run=False, confirmed_scanned=scanned,
        skipped_non_default_category=preview["skipped_non_default_category"], no_match_count=preview["no_match_count"],
        unchanged_count=preview["unchanged_count"], conflict_count=preview["changed_count"] - changed, **fields)
        if status == "confirmed" else RuleApplyPendingResponse(pending_scanned=scanned, **fields))
    mark_idempotency_succeeded(db, claim.row, resource_type="rule_application_batch", resource_id=public_id,
        response_body=receipt.model_dump(mode="json"))
    db.commit()
    return receipt
