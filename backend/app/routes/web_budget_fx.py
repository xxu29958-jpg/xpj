"""Manual FX editing returns to the original money task through the existing rate owner."""

from datetime import date
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    preserve_original_ledger_form,
    templates,
)
from app.schemas import ExchangeRateRequest
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.currency_common import normalize_currency_code, supported_currency_codes
from app.services.exchange_rate_service import list_exchange_rates, set_exchange_rate_idempotently
from app.services.spending_contract_service import current_accounting_month

router = APIRouter(prefix="/rates", tags=["web"])
_TASK_FIELDS = ("ledger_id", "month", "home_currency_code", "savings_target_yuan", "reserved_buffer_yuan",
    "return_to", "granularity", "ranking_metric", "merchant_category")
_RATE_FIELDS = ("currency_code", "rate_date", "rate_to_cny", "expected_row_version", "idempotency_key")


class BudgetRateForm(BaseModel):
    """Raw native fields survive validation before the command owner parses them."""

    ledger_id: str = ""
    month: str = ""
    home_currency_code: str = ""
    savings_target_yuan: str = ""
    reserved_buffer_yuan: str = ""
    return_to: str = ""
    granularity: str = ""
    ranking_metric: str = ""
    merchant_category: str = ""
    currency_code: str = ""
    rate_date: str = ""
    rate_to_cny: str = ""
    expected_row_version: str = ""
    idempotency_key: str = ""
    review_latest: str = ""


def _task_return(values):
    params = {"month": values["month"], "home_currency_code": values["home_currency_code"]}
    if values["return_to"] == "reports":
        params.update(granularity=values["granularity"] or "day", ranking_metric=values["ranking_metric"] or "amount",
            merchant_category=values["merchant_category"])
        return "/web/reports", params, "期间报表"
    params.update(savings_target_yuan=values["savings_target_yuan"], reserved_buffer_yuan=values["reserved_buffer_yuan"])
    return "/web/budget-advise", params, "预算"


def _current_rates(db, selected, values):
    return list_exchange_rates(db, tenant_id=selected,
        currency_code=values["currency_code"] or None,
        home_currency_code=values["home_currency_code"],
        rate_date=date.fromisoformat(values["rate_date"]) if values["rate_date"] else None)


def _review_rate(db, selected, values, *, keep_value):
    if not values["currency_code"] or not values["rate_date"]:
        raise AppError("invalid_request", "请选择原币种和换算日期。", status_code=422)
    rates = _current_rates(db, selected, values)
    current = rates[0] if rates else None
    values.update(expected_row_version=str(current.row_version if current else 0), idempotency_key=str(uuid4()))
    if current is not None and not keep_value:
        values["rate_to_cny"] = str(current.rate_to_cny)


def _render_rates(request, db, options, selected, values, *, error=None, conflict=False, status_code=200):
    try:
        rates = _current_rates(db, selected, values)
    except (AppError, ValueError):
        rates = []
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="人工汇率")
    path, params, label = _task_return(values)
    ctx.update(values=values, rates=rates, error=error, conflict=conflict,
        rate_task={key: values[key] for key in _TASK_FIELDS}, currency_codes=sorted(supported_currency_codes()),
        return_href=path + "?" + urlencode({"ledger_id": values["ledger_id"], **params}), return_label=label)
    return templates.TemplateResponse(request=request, name="budget_rates.html", context=ctx,
        status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("", response_class=HTMLResponse)
def page_budget_rates(request: Request, db: Session = Depends(get_db), _local: None = LocalOnly) -> HTMLResponse:
    values = {key: request.query_params.get(key, "") for key in (*_TASK_FIELDS, *_RATE_FIELDS)}
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, values["ledger_id"] or None, options, request=request)
    values.update(ledger_id=selected, month=values["month"] or current_accounting_month(),
        home_currency_code=normalize_currency_code(values["home_currency_code"] or require_runtime_home_currency_code(db)),
        savings_target_yuan=values["savings_target_yuan"] or "0", reserved_buffer_yuan=values["reserved_buffer_yuan"] or "0",
        idempotency_key=str(uuid4()), expected_row_version="0")
    error = None
    if values["currency_code"] and values["rate_date"]:
        try:
            _review_rate(db, selected, values, keep_value=False)
        except (AppError, ValueError) as exc:
            error = exc.message if isinstance(exc, AppError) else "请检查换算日期。"
    return _render_rates(request, db, options, selected, values, error=error)


def _rate_payload(values):
    version = values["expected_row_version"]
    if not version.isascii() or not version.isdecimal():
        raise AppError("state_conflict", "请核对当前汇率。原输入已保留。", status_code=409)
    return ExchangeRateRequest(currency_code=values["currency_code"], home_currency_code=values["home_currency_code"],
        rate_date=values["rate_date"], rate_to_cny=values["rate_to_cny"], expected_row_version=int(version))


@router.post("", response_class=HTMLResponse)
def save_budget_rate(request: Request, form: BudgetRateForm = Form(),
    db: Session = Depends(get_db), _local: None = LocalOnly) -> Response:
    raw = form.model_dump()
    values = {key: str(raw.get(key, "")) for key in (*_TASK_FIELDS, *_RATE_FIELDS)}
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, values["ledger_id"] or None, options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields={**values, "review_latest": str(raw.get("review_latest", ""))}, task="保存人工汇率")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    try:
        if raw.get("review_latest") == "true":
            _review_rate(db, selected, values, keep_value=True)
            return _render_rates(request, db, options, selected, values)
        receipt = set_exchange_rate_idempotently(db, tenant_id=selected,
            actor_account_id=resolve_web_actor_account_id(db, request, selected),
            payload=_rate_payload(values), idempotency_key=values["idempotency_key"])
    except (AppError, ValidationError, ValueError) as exc:
        db.rollback()
        conflict = isinstance(exc, AppError) and exc.error in {
            "state_conflict", "idempotency_key_reused", "idempotency_key_required"}
        error = exc.message if isinstance(exc, AppError) else "请检查币种、日期和汇率。原输入已保留。"
        return _render_rates(request, db, options, selected, values, error=error, conflict=conflict,
            status_code=exc.status_code if isinstance(exc, AppError) else 422)
    path, params, _ = _task_return(values)
    return _web_redirect(path, ledger_id=selected, **params,
        msg=f"{receipt.currency_code} → {receipt.home_currency_code} · {receipt.rate_date} 的提交已确认。以下按当前汇率重新计算。")
