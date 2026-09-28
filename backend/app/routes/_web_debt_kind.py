"""The native type correction retains its original choice, version and receipt."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.routes._web_debt_kind_forms import render_kind_recovery
from app.routes._web_debt_repayment import require_repayment_binding
from app.routes._web_debt_write import repayment_scope
from app.routes.web_common import (
    _require_selected_ledger_write,
    parse_form_row_version_token,
)
from app.schemas import DebtKindSetRequest

KIND_FIELDS = ("debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "debt_kind")


def kind_outcome(request, db, *, options, selected_id, public_id, values=None,
                 error="", result="", status_code=200, ack=None, rejected=False):
    from app.routes.web_debts import _render_debt_detail

    try:
        return _render_debt_detail(request, db, options=options, selected_id=selected_id,
            public_id=public_id, action_kind="kind", action_draft=values, action_error=error,
            kind_result=result, kind_ack=ack, kind_rejected=rejected, status_code=status_code)
    except (AppError, SQLAlchemyError):
        db.rollback()
        return render_kind_recovery(request, db, options=options, selected_id=selected_id,
            public_id=public_id, values=values, error=error, result=result, ack=ack,
            rejected=rejected, status_code=status_code)


def _kind_error(exc, *, attempted):
    status, error = 422, "请选择正确的偿还方式。"
    code = ""
    if isinstance(exc, AppError):
        status, error, code = exc.status_code, exc.message, exc.error
    elif isinstance(exc, SQLAlchemyError):
        status, error = 503, "原更正结果暂未确认，请继续核实原提交。"
    result = "submitted" if status >= 500 or code == "idempotency_key_in_progress" else "blocked"
    if not attempted and status == 422:
        result = "rejected"
    if code == "debt_kind_original_requires_review":
        result = "accepted-review"
    return {"status_code": status, "error": error, "result": result, "rejected": code == "state_conflict"}


def submit_kind(request, db, *, options, selected_id, public_id, actor_account_id, values, writer):
    attempted = False
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id)
        _require_selected_ledger_write(options, selected_id)
        expected = parse_form_row_version_token(values["expected_row_version"])
        if expected is None:
            raise AppError("state_conflict", "原更正缺少有效版本，请核对原记录。", status_code=409)
        payload = DebtKindSetRequest(debt_kind=values["debt_kind"].strip(), expected_row_version=expected)
        attempted = True
        receipt = writer(db, tenant_id=selected_id, actor_account_id=actor_account_id(), public_id=public_id,
            payload=payload, idempotency_key=values["idempotency_key"].strip() or None)
    except (AppError, ValidationError, SQLAlchemyError) as exc:
        db.rollback()
        return kind_outcome(request, db, options=options, selected_id=selected_id, public_id=public_id,
            values=values, **_kind_error(exc, attempted=attempted))
    ack = {"scope": repayment_scope(request, db), "clientRef": values["idempotency_key"],
        "resultPublicId": receipt.public_id, "values": {name: values[name] for name in KIND_FIELDS},
        "debtKind": receipt.debt_kind}
    return kind_outcome(request, db, options=options, selected_id=selected_id, public_id=public_id, ack=ack)
