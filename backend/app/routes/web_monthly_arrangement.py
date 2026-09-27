"""Native arrangement saves retain the original form until the command is known."""

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
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
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.schemas._monthly_arrangement import MonthlyArrangementSaveRequest
from app.services.currency_common import major_amount_to_minor, minor_amount_label, normalize_currency_code
from app.services.monthly_arrangement_service import (
    list_monthly_arrangement_history,
    read_monthly_arrangement,
    review_monthly_arrangement_save,
    save_monthly_arrangement,
)
from app.services.spending_contract_service import clean_month

router = APIRouter(tags=["web"])


class MonthlyArrangementForm(BaseModel):
    ledger_id: str = ""
    month: str = ""
    home_currency_code: str = ""
    arrangement_currency_code: str = ""
    savings_target_yuan: str = ""
    reserved_buffer_yuan: str = ""
    expected_row_version: str = ""
    idempotency_key: str = ""
    review_latest: bool = False


def arrangement_payload(form: MonthlyArrangementForm) -> MonthlyArrangementSaveRequest:
    version = parse_form_row_version_token(form.expected_row_version)
    if form.expected_row_version != "null" and version is None:
        raise AppError("state_conflict", "安排版本无法确认，请保留输入并核对当前版本。", status_code=409)
    source = form.arrangement_currency_code or form.home_currency_code
    if not source:
        raise AppError("invalid_request", "请选择原输入使用的币种，金额已保留。", status_code=422)
    home = normalize_currency_code(source)
    return MonthlyArrangementSaveRequest(home_currency_code=home, expected_row_version=version,
        savings_target_cents=major_amount_to_minor(form.savings_target_yuan or "0", home),
        reserved_buffer_cents=major_amount_to_minor(form.reserved_buffer_yuan or "0", home))


def _retained_response(request, db, form, *, error=None, message=None, conflict=False, status_code=200):
    from app.routes.web_budget_advise import _render_budget_advise

    return _render_budget_advise(request, db=db, ledger_id=form.ledger_id, month=form.month,
        home_currency_code=form.home_currency_code, savings_target_yuan=form.savings_target_yuan,
        arrangement_currency_code=form.arrangement_currency_code or None,
        reserved_buffer_yuan=form.reserved_buffer_yuan, expected_row_version=form.expected_row_version,
        idempotency_key=form.idempotency_key, run_advise=False, allow_outbound=False,
        message=message, save_error=error, save_conflict=conflict, response_status=status_code)


@router.post("/save", response_class=HTMLResponse)
def save_arrangement_form(request: Request, form: MonthlyArrangementForm = Form(),
    db: Session = Depends(get_db), _local: None = LocalOnly) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected,
        fields=form.model_dump(), task="保存本月储蓄与备用金安排")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected)
    month = clean_month(form.month)
    try:
        if form.review_latest:
            accepted = review_monthly_arrangement_save(db, tenant_id=selected, month=month,
                idempotency_key=form.idempotency_key)
            latest = read_monthly_arrangement(db, tenant_id=selected, month=month)
            if latest and latest.home_currency_code != (form.arrangement_currency_code or form.home_currency_code):
                return _retained_response(request, db, form, error="当前安排与原输入币种不同，原金额已保留。请打开当前安排重新编辑。",
                    conflict=True, status_code=409)
            form.expected_row_version = str(latest.row_version) if latest else "null"
            if accepted:
                form.idempotency_key = str(uuid4())
            return _retained_response(request, db, form, message="已保留输入并载入当前版本，请核对后再保存。")
        save_monthly_arrangement(db, tenant_id=selected, month=month, payload=arrangement_payload(form),
            actor_account_id=resolve_web_actor_account_id(db, request, selected), idempotency_key=form.idempotency_key)
    except AppError as exc:
        return _retained_response(request, db, form, error=exc.message, status_code=exc.status_code,
            conflict=exc.error in {"state_conflict", "idempotency_key_reused"})
    except ValidationError:
        return _retained_response(request, db, form, error="请核对金额，储蓄和备用金须为当前币种支持的非负金额。",
            status_code=422)
    except SQLAlchemyError:
        db.rollback()
        return _retained_response(request, db, form, error="保存结果尚未确认，原提交已保留，请原样重试。", status_code=503)
    return _web_redirect("/web/budget-advise", selected, month=month, home_currency_code=form.home_currency_code or None,
        msg="本月安排已保存，其他端可读取同一份安排。")


@router.get("/history", response_class=HTMLResponse)
def arrangement_history_page(request: Request, ledger_id: str | None = None, month: str = Query(...),
    before_version: int | None = Query(default=None, ge=1), db: Session = Depends(get_db),
    _local: None = LocalOnly) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    history = list_monthly_arrangement_history(db, tenant_id=selected, month=clean_month(month),
        before_version=before_version, limit=20)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="安排修改记录")
    ctx.update(history=history, arrangement_amount=minor_amount_label)
    return templates.TemplateResponse(request=request, name="monthly_arrangement_history.html", context=ctx,
        headers={"Cache-Control": "no-store"})
