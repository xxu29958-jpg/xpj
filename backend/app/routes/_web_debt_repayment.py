"""One native repayment form, including recovery without a readable Debt projection."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes import _web_debt_write
from app.routes.web_common import _base_ctx, _currency_input_view, templates
from app.services.currency_common import supported_currency_codes
from app.services.manual_expense_draft_presenter import manual_draft_scope
from app.services.time_service import now_utc

REPAYMENT_FIELDS = (
    "debt_public_id", "ledger_id", "origin_binding", "home_currency_code",
    "expected_row_version", "amount_major", "paid_at", "paid_at_timezone",
)


def repayment_scope(request: Request, db: Session) -> dict[str, str]:
    auth = getattr(request.state, "web_session_auth", None)
    return manual_draft_scope(db, auth) if auth is not None else {}


def require_repayment_binding(request: Request, db: Session, *, values: dict, public_id: str) -> None:
    scope = repayment_scope(request, db)
    try:
        original = json.loads(values["origin_binding"]) if values["origin_binding"] else {}
    except (ValueError, TypeError) as exc:
        raise AppError("session_binding_changed", "原提交的身份信息无法读取，输入仍保留。", status_code=409) from exc
    if original != scope or (scope and values["ledger_id"] != scope["ledgerId"]):
        raise AppError("session_binding_changed", "账号、账本或浏览器身份已变化。请回到原身份核对这次还款，原提交不会转移。", status_code=409)
    if values["debt_public_id"] and values["debt_public_id"] != public_id:
        raise AppError("debt_target_changed", "请回到原欠款核对这次还款。", status_code=409)


def repayment_context(
    request: Request, db: Session, *, selected_id: str, public_id: str,
    currency_code: str = "", expected_row_version: str = "", can_create: bool = False,
    can_recover: bool = False,
    values: dict[str, str] | None = None, error: str = "", result: str = "",
    ack: dict | None = None, rejected: bool = False,
) -> dict:
    scope = repayment_scope(request, db)
    zone = _web_debt_write.accounting_zone()
    initial = {
        "debt_public_id": public_id, "ledger_id": selected_id,
        "origin_binding": json.dumps(scope, ensure_ascii=False, sort_keys=True),
        "home_currency_code": currency_code, "expected_row_version": expected_row_version,
        "amount_major": "", "paid_at": now_utc().astimezone(zone).date().isoformat() if can_create else "",
        "paid_at_timezone": zone.key if can_create else "", "idempotency_key": str(uuid4()) if can_create else "",
    }
    if values is not None:
        initial.update(values)
    code = initial["home_currency_code"]
    replacement = None
    if rejected and can_create and values is not None:
        try:
            require_repayment_binding(request, db, values=values, public_id=public_id)
        except AppError:
            pass
        else:
            replacement = {"clientRef": str(uuid4()), "values": {
                **{key: initial[key] for key in REPAYMENT_FIELDS},
                "expected_row_version": expected_row_version,
            }}
    return {
        "public_id": public_id, "scope": scope, "values": initial, "error": error,
        "result": result, "can_create": can_create, "visible": can_create or values is not None,
        "can_recover": can_recover,
        "currency_input": _currency_input_view(code) if code in supported_currency_codes() else None,
        "ack": ack,
        "replacement": replacement,
    }


def render_repayment_recovery(
    request: Request, db: Session, *, options, selected_id: str, public_id: str,
    values: dict[str, str] | None = None, error: str = "", result: str = "",
    status_code: int = 503, ack: dict | None = None,
):
    # The identity/installation scope is still authoritative. No Debt fold,
    # history, side counts or inferred latest OCC is needed to retain a command.
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id, page_title="核对还款")
    ctx["repayment_form"] = repayment_context(
        request, db, selected_id=selected_id, public_id=public_id,
        values=values, error=error, result=result, ack=ack,
        can_recover=_web_debt_write._debt_write_gate(options, selected_id),
    )
    return templates.TemplateResponse(request=request, name="debt_repayment_recovery.html", context=ctx, status_code=status_code)
