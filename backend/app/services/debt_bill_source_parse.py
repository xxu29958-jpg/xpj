"""Synchronous suggestions over an accepted original; no financial or job writer."""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiIdempotencyKey
from app.schemas.debt_bill_capture import DebtBillParseOutcome
from app.services.debt_bill_capture_service import (
    CAPTURE_RESOURCE,
    accepted_capture_command,
    authorize_capture_write,
    get_capture,
    read_capture_original,
    require_pending_capture,
)
from app.services.debt_bill_parse_service import get_debt_bill_provider
from app.services.idempotency import claim_idempotent_request, fingerprint_request, mark_idempotency_succeeded
from app.services.optimistic_concurrency import bump_row_version
from app.services.time_service import now_utc
from app.tenants import AuthContext

_PARSE = "parse_debt_bill_source"


def parse_captured_bill(db: Session, *, auth: AuthContext, public_id: str,
                        expected_row_version: int, key: str) -> DebtBillParseOutcome:
    body = {"actor_account_id": auth.account_id}
    fingerprint = fingerprint_request(operation=_PARSE, target_id=public_id,
        body=body, expected_row_version=expected_row_version)
    authorize_capture_write(db, auth)
    accepted = accepted_capture_command(db, tenant_id=auth.ledger_id, key=key, fingerprint=fingerprint)
    if accepted is not None:
        return DebtBillParseOutcome.model_validate(accepted)
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    if source.parse_attempt_key == key:
        if source.parse_request_fingerprint != fingerprint:
            raise AppError("idempotency_key_reused", status_code=422)
        return DebtBillParseOutcome.model_validate(source.parse_outcome)
    require_pending_capture(source, expected_row_version)
    with read_capture_original(source) as original:
        data, media_type = original.path.read_bytes(), original.media_type
    # End all identity/source reads before model execution; no transaction lock spans inference.
    db.rollback()
    provider = get_debt_bill_provider()
    suggestion, error_code = None, None
    try:
        suggestion = asdict(provider.parse(data, media_type))
    except AppError as error:
        error_code = error.error
    return _publish_outcome(db, auth=auth, public_id=public_id, expected_row_version=expected_row_version,
        key=key, body=body, fingerprint=fingerprint, provider=type(provider).__name__,
        suggestion=suggestion, error_code=error_code)


def _publish_outcome(db: Session, *, auth: AuthContext, public_id: str, expected_row_version: int,
                     key: str, body: dict, fingerprint: str, provider: str,
                     suggestion: dict | None, error_code: str | None) -> DebtBillParseOutcome:
    authorize_capture_write(db, auth)
    claim = claim_idempotent_request(db, idempotency_key=key, tenant_id=auth.ledger_id, operation=_PARSE,
        target_id=public_id, body=body, expected_row_version=expected_row_version, target_type=CAPTURE_RESOURCE)
    if claim is None:
        return DebtBillParseOutcome.model_validate(accepted_capture_command(
            db, tenant_id=auth.ledger_id, key=key, fingerprint=fingerprint))
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id, lock=True)
    require_pending_capture(source, expected_row_version)
    bump_row_version(source)
    source.updated_at = now_utc()
    db.flush()
    result = DebtBillParseOutcome(public_id=public_id, attempt_key=key, row_version=source.row_version,
        status="failed" if error_code else "succeeded", provider=provider,
        suggestion=suggestion, error_code=error_code, completed_at=source.updated_at)
    source.parse_attempt_key, source.parse_request_fingerprint = key, fingerprint
    source.parse_outcome = result.model_dump(mode="json")
    mark_idempotency_succeeded(db, claim, resource_type=CAPTURE_RESOURCE,
        resource_id=public_id, response_body=result.model_dump(mode="json"))
    db.commit()
    return result


def read_parse_outcome(db: Session, *, auth: AuthContext, public_id: str, key: str) -> DebtBillParseOutcome:
    source = get_capture(db, tenant_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    row = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == auth.ledger_id,
        ApiIdempotencyKey.idempotency_key == key, ApiIdempotencyKey.operation == _PARSE,
        ApiIdempotencyKey.target_id == public_id, ApiIdempotencyKey.status == "succeeded"))
    if row is not None:
        return DebtBillParseOutcome.model_validate(row.response_body)
    if source.parse_attempt_key == key:
        return DebtBillParseOutcome.model_validate(source.parse_outcome)
    raise AppError("debt_bill_parse_not_found", status_code=404)
