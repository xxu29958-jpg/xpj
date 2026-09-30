"""Original capture review using the existing browser draft and command owners."""

from __future__ import annotations

import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.routes._web_debt_money import parse_web_debt_major_minor
from app.routes._web_debt_repayment import require_repayment_binding
from app.routes._web_debt_write import _debt_write_gate, repayment_scope
from app.routes.web_common import (
    _base_ctx,
    _minor_amount_value,
    _require_selected_ledger_write,
    parse_form_row_version_token,
    templates,
)
from app.schemas import RepaymentDraftConfirmRequest
from app.services.currency_common import normalize_currency_code, supported_currency_codes
from app.services.debt_service import dismiss_repayment_draft, list_repayment_draft_audit_for_account
from app.services.debt_service._repayment_draft import get_repayment_draft_response
from app.services.repayment_draft_command_service import confirm_repayment_draft_idempotently

REVIEW_FIELDS = (
    "draft_public_id", "ledger_id", "origin_binding", "review_action",
    "target_with_expected_row_version", "original_currency", "original_amount",
)


def _initial_review_values(scope, selected_id, public_id, row, can_create):
    suggested = next((item for item in row.target_debts if item.public_id == row.suggested_debt_public_id), None) if row else None
    return {
        "draft_public_id": public_id, "ledger_id": selected_id,
        "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
        "review_action": "confirm",
        "target_with_expected_row_version": f"{suggested.public_id}:{suggested.row_version}" if suggested else "",
        "original_currency": row.original_currency_code if row else "",
        "original_amount": _minor_amount_value(row.original_amount_minor, row.original_currency_code) if row else "",
        "idempotency_key": str(uuid4()) if can_create else "",
    }


def render_review(request, db, *, options, selected_id, public_id, account_id,
                  values=None, error="", result="", rejected=False, ack=None, status_code=200):
    from app.routes.web_repayment_drafts import _audit_row_view

    scope = repayment_scope(request, db)
    row, read_error = None, ""
    try:
        rows = list_repayment_draft_audit_for_account(
            db, account_id=account_id, tenant_id=selected_id, public_id=public_id)
        row = rows[0] if rows else None
        if row is None:
            read_error = "原采集不在当前账号和账本中。请回到原身份查看。"
            if not ack and not error:
                status_code = 404
    except (AppError, SQLAlchemyError):
        db.rollback()
        read_error = "当前采集暂时无法读取。浏览器保留的原输入仍可在下方核对。"
        if not ack and not error:
            status_code = 503
    can_recover = _debt_write_gate(options, selected_id)
    can_create = bool(row and row.status == "pending" and can_recover)
    view = _audit_row_view(row) if row else None
    initial = _initial_review_values(scope, selected_id, public_id, row, can_create)
    if values is not None:
        initial.update(values)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对还款采集")
    ctx.update(row=view, read_error=read_error, currencies=supported_currency_codes(), review={
        "public_id": public_id, "scope": scope, "values": initial,
        "can_create": can_create, "can_recover": can_recover, "visible": can_create or values is not None,
        "error": error, "result": result, "rejected": rejected, "ack": ack,
    })
    return templates.TemplateResponse(request=request, name="repayment_review.html", context=ctx, status_code=status_code)


def review_confirmation(values, captured):
    target, separator, token = values["target_with_expected_row_version"].rpartition(":")
    expected = parse_form_row_version_token(token)
    if not separator or not target or expected is None or expected < 0:
        raise AppError("invalid_request", "请选择欠款并核对它的当前版本。", status_code=422)
    code = normalize_currency_code(values["original_currency"])
    minor = parse_web_debt_major_minor(values["original_amount"].strip(), currency_code=code, allow_negative=False)
    if code == captured.original_currency_code and minor == captured.original_amount_minor:
        # An unchanged Expense bridge can already have frozen home money. Omitting
        # the override preserves that fact; reviewing different money is explicit.
        return RepaymentDraftConfirmRequest(target_debt_public_id=target, expected_row_version=expected)
    return RepaymentDraftConfirmRequest(target_debt_public_id=target, expected_row_version=expected,
        original_currency=code, original_amount=_minor_amount_value(minor, code))


def _review_error(exc):
    from app.routes.web_repayment_drafts import _error_message

    status, code, error = 422, "invalid_request", "请填写有效的币种、金额和欠款。"
    if isinstance(exc, AppError):
        status, code, error = exc.status_code, exc.error, _error_message(exc)
    elif isinstance(exc, SQLAlchemyError):
        status, code, error = 503, "result_unknown", "处理结果暂未确认，请继续核实原提交。"
    unknown = status >= 500 or code == "idempotency_key_in_progress"
    rejected = not unknown and code not in {
        "session_binding_changed", "debt_target_changed", "idempotency_key_reused",
        "permission_denied", "ledger_write_forbidden", "repayment_draft_not_found",
    } and status not in {401, 403, 404, 429}
    return {"status_code": status, "error": error, "result": "submitted" if unknown else "blocked", "rejected": rejected}


def submit_review(request, db, *, options, selected_id, public_id, account_id, values):
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id, target_field="draft_public_id")
        _require_selected_ledger_write(options, selected_id)
        scope = repayment_scope(request, db)
        if values["review_action"] == "confirm":
            captured = get_repayment_draft_response(db, tenant_id=selected_id, actor_account_id=account_id, public_id=public_id)
            payload = review_confirmation(values, captured)
            receipt = confirm_repayment_draft_idempotently(
                db, tenant_id=selected_id, actor_account_id=account_id, public_id=public_id,
                payload=payload, idempotency_key=values["idempotency_key"].strip() or None)
        elif values["review_action"] == "dismiss":
            receipt = dismiss_repayment_draft(db, tenant_id=selected_id, actor_account_id=account_id, public_id=public_id, commit=True)
        else:
            raise AppError("invalid_request", "请选择记为还款或忽略通知。", status_code=422)
    except (AppError, ValidationError, SQLAlchemyError) as exc:
        db.rollback()
        return render_review(request, db, options=options, selected_id=selected_id, public_id=public_id,
            account_id=account_id, values=values, **_review_error(exc))
    ack = {"scope": scope, "clientRef": values["idempotency_key"], "resultPublicId": receipt.public_id,
        "values": {name: values[name] for name in REVIEW_FIELDS},
        "repaymentPublicId": receipt.committed_repayment_public_id, "status": receipt.status}
    return render_review(request, db, options=options, selected_id=selected_id, public_id=public_id, account_id=account_id, ack=ack)
