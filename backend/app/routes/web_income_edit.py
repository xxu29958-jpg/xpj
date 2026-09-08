"""Native income correction delegates publication to the existing revision owner."""

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _currency_input_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.routes.web_income_plans import _parse_pay_day, _parse_yuan
from app.schemas import IncomePlanUpdateRequest
from app.services.currency_common import minor_amount_value
from app.services.income_plan_service import get_income_plan
from app.services.income_plan_service._delivery import update_income_plan_idempotently
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/web/income-plans", tags=["web"])


def _edit_scope(request: Request, db: Session, ledger_id: str, public_id: str):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected)
    return options, selected, get_income_plan(db, tenant_id=selected, public_id=public_id)


def _render_editor(
    request: Request, db: Session, options, selected: str, plan,
    *, intent_month: str, values: dict[str, str] | None = None,
    error: str | None = None, conflict: bool = False, status_code: int = 200,
) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected)
    current = {
        "label": plan.label, "source_type": plan.source_type, "frequency": plan.frequency,
        "income_month": plan.income_month or "", "pay_day": str(plan.pay_day),
        "amount_yuan": minor_amount_value(plan.amount_cents, plan.home_currency_code),
        "expected_row_version": str(plan.row_version),
    }
    ctx.update(
        plan=plan, current=current, currency_input=_currency_input_view(plan.home_currency_code), values=values if values is not None else {
            **current, "intent_month": intent_month, "idempotency_key": str(uuid4()),
        }, error=error, conflict=conflict, review_month=current_accounting_month(),
    )
    return templates.TemplateResponse(
        request=request, name="income_edit.html", context=ctx, status_code=status_code,
    )


@router.get("/{public_id}/edit", response_class=HTMLResponse)
def web_income_edit(
    request: Request, public_id: str,
    intent_month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), ledger_id: str = "",
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected, plan = _edit_scope(request, db, ledger_id, public_id)
    return _render_editor(request, db, options, selected, plan, intent_month=intent_month)


def _edit_payload(values: dict[str, str], *, currency_code: str) -> IncomePlanUpdateRequest:
    version = parse_form_row_version_token(values["expected_row_version"])
    if version is None:
        raise AppError("state_conflict", status_code=409)
    return IncomePlanUpdateRequest(
        expected_row_version=version, intent_month=values["intent_month"],
        label=values["label"], source_type=values["source_type"], frequency=values["frequency"],
        income_month=(values["income_month"].strip() or None) if values["frequency"] == "one_time" else None,
        amount_cents=_parse_yuan(values["amount_yuan"], currency_code=currency_code, label="预计收入金额"),
        pay_day=_parse_pay_day(values["pay_day"]),
    )


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_income_save(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), label: str = Form(default=""),
    source_type: str = Form(default=""), frequency: str = Form(default=""),
    income_month: str = Form(default=""), amount_yuan: str = Form(default=""),
    pay_day: str = Form(default=""), intent_month: str = Form(default=""),
    expected_row_version: str = Form(default=""), idempotency_key: str = Form(default=""),
    review_latest: bool = Form(default=False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options, selected, plan = _edit_scope(request, db, ledger_id, public_id)
    values = {
        "label": label, "source_type": source_type, "frequency": frequency,
        "income_month": income_month, "amount_yuan": amount_yuan, "pay_day": pay_day,
        "intent_month": intent_month, "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
    }
    if review_latest:
        # The labelled review action prepares, but never publishes, a new intent.
        values.update(intent_month=current_accounting_month(), expected_row_version=str(plan.row_version), idempotency_key=str(uuid4()))
        return _render_editor(request, db, options, selected, plan, intent_month=values["intent_month"], values=values)
    try:
        payload = _edit_payload(values, currency_code=plan.home_currency_code)
        update_income_plan_idempotently(
            db, tenant_id=selected, public_id=public_id, payload=payload,
            actor_account_id=resolve_web_actor_account_id(db, request, selected), idempotency_key=idempotency_key,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        conflict = isinstance(exc, AppError) and exc.error in {"state_conflict", "idempotency_key_reused"}
        error = exc.message if isinstance(exc, AppError) else "请检查名称、频率、月份和金额。输入已保留。"
        if conflict:
            error = "计划已有较新变更。你的输入和原生效月份已保留，请核对当前计划后再保存。"
            if exc.error == "idempotency_key_reused":
                error = "这份表单已经提交过。新的修改尚未保存，请核对当前计划和生效月份后再保存。"
        return _render_editor(
            request, db, options, selected, plan, intent_month=intent_month,
            values=values, error=error, conflict=conflict,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _web_redirect("/web/income-plans", selected, message="收入计划修改已保存")
