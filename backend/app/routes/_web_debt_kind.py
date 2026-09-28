"""The native type correction retains its original choice, version and receipt."""

from __future__ import annotations

import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.routes._web_debt_repayment import require_repayment_binding
from app.routes._web_debt_write import _debt_write_gate, repayment_scope
from app.routes.web_common import (
    _base_ctx,
    _require_selected_ledger_write,
    parse_form_row_version_token,
    templates,
)
from app.schemas import DebtKindSetRequest

KIND_FIELDS = ("debt_public_id", "ledger_id", "origin_binding", "expected_row_version", "debt_kind")


def kind_context(request, db, *, selected_id, public_id, expected="", debt_kind="unspecified",
                 can_create=False, can_recover=False, values=None, error="", result="", ack=None, rejected=False):
    scope = repayment_scope(request, db)
    initial = {"debt_public_id": public_id, "ledger_id": selected_id,
        "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
        "expected_row_version": expected, "debt_kind": debt_kind,
        "idempotency_key": str(uuid4()) if can_create else ""}
    if values is not None:
        initial.update(values)
    return {"public_id": public_id, "scope": scope, "values": initial, "visible": can_create or values is not None,
        "can_create": can_create, "can_recover": can_recover, "error": error, "result": result,
        "ack": ack, "rejected": rejected}


def add_kind_detail_context(request, db, *, ctx, debt, selected_id, public_id, kind, values, error, result, ack, rejected):
    can_view_original = not ctx["debt"]["is_member"] or debt.ledger_id is not None and debt.viewer_is_debtor is True
    ctx["kind_form"] = kind_context(request, db, selected_id=selected_id, public_id=public_id,
        expected=str(debt.row_version), debt_kind=debt.debt_kind,
        can_create=ctx["can_write"] and ((not ctx["debt"]["is_member"] and debt.status == "open") or ctx["can_change_member_kind"]),
        can_recover=ctx["can_write"] and can_view_original,
        values=values if kind == "kind" else None,
        error=error if kind == "kind" else "", result=result, ack=ack, rejected=rejected)
    ctx["kind_form"]["can_view_original"] = can_view_original
    if kind == "kind":
        ctx["action_form"]["fallback"] = False


def kind_outcome(request, db, *, options, selected_id, public_id, values=None,
                 error="", result="", status_code=200, ack=None, rejected=False):
    from app.routes.web_debts import _render_debt_detail

    try:
        return _render_debt_detail(request, db, options=options, selected_id=selected_id,
            public_id=public_id, action_kind="kind", action_draft=values, action_error=error,
            kind_result=result, kind_ack=ack, kind_rejected=rejected, status_code=status_code)
    except (AppError, SQLAlchemyError):
        db.rollback()
        ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对原偿还方式")
        ctx["kind_form"] = kind_context(request, db, selected_id=selected_id, public_id=public_id,
            can_recover=_debt_write_gate(options, selected_id), values=values,
            error=error, result=result, ack=ack, rejected=rejected)
        ctx["kind_detail_error"] = "当前详情暂时无法刷新，请稍后重新读取；原提交结果和输入仍保留在此页。"
        return templates.TemplateResponse(request=request, name="debt_kind_recovery.html", context=ctx, status_code=status_code)


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
