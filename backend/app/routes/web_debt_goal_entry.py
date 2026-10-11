"""Debt-goal tasks bind browser drafts to the existing domain commands."""

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    rendered_draft_scope,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    _with_ledger,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.routes.web_debt_goal_views import _debt_choice_view, _debt_goal_view, _web_viewer_account_id
from app.schemas import DebtGoalLinksReplaceRequest, DebtGoalTargetDateRequest, GoalCreateRequest
from app.services.debt_service import list_debts
from app.services.goal_debt_repayment_service import (
    create_debt_repayment_goal_idempotently,
    replace_debt_repayment_goal_links_idempotently,
    set_debt_goal_target_date_idempotently,
)
from app.services.goal_service import get_goal_response

router = APIRouter(prefix="/web/debt-goals", tags=["web"])
_LABELS = {"create": "新建还债目标", "links": "这个目标关联哪些欠款", "target-date": "调整还清日期"}
_BUTTONS = {"create": "创建目标", "links": "保存关联", "target-date": "保存日期"}


def _entry_goal(db, selected_id, public_id):
    if not public_id:
        return None
    goal = get_goal_response(db, tenant_id=selected_id, public_id=public_id)
    if goal.goal_type != "debt_repayment":
        raise AppError("goal_not_found", status_code=404)
    return _debt_goal_view(goal)


def _date_input_type(raw):
    try:
        return "date" if not raw or date.fromisoformat(raw).isoformat() == raw else "text"
    except ValueError:
        return "text"


def _render_entry(request, db, options, selected_id, public_id, task, *, values=None,
                  error=None, status_code=200, draft_result=""):
    goal = _entry_goal(db, selected_id, public_id)
    values = values if values is not None else {
        "ledger_id": selected_id, "name": goal["name"] if goal else "",
        "debt_public_ids": goal["linked_debt_ids"] if goal else [],
        "target_date": goal["target_date_value"] if goal else "",
        "expected_row_version": str(goal["row_version"]) if goal else "",
        "idempotency_key": str(uuid4()),
    }
    scope, binding_required = rendered_draft_scope(db, request, values.get("draft_scope"))
    selected = values["debt_public_ids"]
    linked = goal["linked_debt_ids"] if goal else []
    debts = list_debts(db, tenant_id=selected_id,
        viewer_account_id=_web_viewer_account_id(request, db, selected_id)).items
    choices = [_debt_choice_view(debt) for debt in debts
        if debt.status == "open" or debt.public_id in selected or debt.public_id in linked]
    known = {choice["public_id"] for choice in choices}
    choices += [{"public_id": public_id, "name": "原选择的欠款", "meta": "当前不可读取，请核对原关联。",
        "status": "unavailable", "status_label": "待核对"} for public_id in selected if public_id not in known]
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    ctx.update(goal=goal, values=values, task=task, choices=choices, error=error,
        date_input_type=_date_input_type(values["target_date"]),
        entry_title=_LABELS[task], entry_button=_BUTTONS[task],
        entry_action="/web/debt-goals/" + (f"{public_id}/{task}" if public_id else "create"),
        entry_href=_with_ledger("/web/debt-goals/" + (f"{public_id}/{task}" if public_id else "new"), selected_id),
        task_id=f"{public_id}:{task}" if public_id else "", public_id=public_id,
        debtgoal_draft_scope=scope, draft_result=draft_result, binding_required=binding_required,
        return_href=_with_ledger("/web/debt-goals", selected_id) + (f"#goal-{public_id}" if public_id else ""))
    return templates.TemplateResponse(request=request, name="debt_goal_entry.html", context=ctx,
        status_code=status_code, headers={"Cache-Control": "no-store"})


@router.get("/new", response_class=HTMLResponse)
@router.get("/{public_id}/links", response_class=HTMLResponse)
@router.get("/{public_id}/target-date", response_class=HTMLResponse)
def web_debt_goal_entry(request: Request, public_id: str = "", ledger_id: str = "",
                        _local: None = LocalOnly, db: Session = Depends(get_db)) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    task = request.url.path.rsplit("/", 1)[1] if public_id else "create"
    return _render_entry(request, db, options, selected_id, public_id, task)


def _submit_entry(db, selected_id, public_id, task, values, *, json_receipt):
    key = values["idempotency_key"].strip() or None
    if task == "create":
        if not values["name"].strip() or not values["debt_public_ids"]:
            raise AppError("invalid_request", "请输入目标名称并至少选择一笔未结清欠款。", status_code=422)
        payload = GoalCreateRequest(name=values["name"].strip(), goal_type="debt_repayment",
            debt_public_ids=values["debt_public_ids"])
        return create_debt_repayment_goal_idempotently(db, tenant_id=selected_id, payload=payload,
            idempotency_key=key, allow_legacy_current=not json_receipt)
    version = parse_form_row_version_token(values["expected_row_version"])
    if version is None:
        raise AppError("state_conflict", status_code=409)
    if task == "links":
        payload = DebtGoalLinksReplaceRequest(expected_row_version=version, debt_public_ids=values["debt_public_ids"])
        return replace_debt_repayment_goal_links_idempotently(db, tenant_id=selected_id, public_id=public_id,
            payload=payload, idempotency_key=key)
    try:
        target = date.fromisoformat(values["target_date"].strip()) if values["target_date"].strip() else None
    except ValueError as exc:
        raise AppError("invalid_request", "请选择正确的还清日期。", status_code=422) from exc
    return set_debt_goal_target_date_idempotently(db, tenant_id=selected_id, public_id=public_id,
        payload=DebtGoalTargetDateRequest(expected_row_version=version, target_date=target), idempotency_key=key)


def _save_entry(request, db, ledger_id, public_id, task, values, review_latest):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft_scope, idempotency_key = values["draft_scope"], values["idempotency_key"]
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, "review_latest": review_latest}, task=_LABELS[task])
    if retained is not None:
        return retained
    try:
        values["draft_scope"] = reviewed_draft_scope(db, request, draft_scope, review=review_latest)
        require_draft_binding(db, request, ledger_id=selected_id,
            draft_scope=values["draft_scope"], require_session=False)
        _require_selected_ledger_write(options, selected_id)
        if review_latest:
            goal = _entry_goal(db, selected_id, public_id)
            values.update(expected_row_version=str(goal["row_version"]) if goal else "",
                prepared_from=idempotency_key, idempotency_key=str(uuid4()))
            return _render_entry(request, db, options, selected_id, public_id, task,
                values=values, draft_result="prepared")
        result = _submit_entry(db, selected_id, public_id, task, values,
            json_receipt="application/json" in request.headers.get("accept", ""))
    except (AppError, ValidationError) as exc:
        db.rollback()
        error = exc if isinstance(exc, AppError) else AppError("invalid_request",
            "至少选择一笔欠款，并检查目标名称。输入已保留。", status_code=422)
        if error.error == "state_conflict":
            error = AppError(error.error, "目标已在其它端更新。输入已保留，请核对当前目标后再保存。", status_code=409)
        if (response := draft_error_response(request, error)) is not None:
            return response
        return _render_entry(request, db, options, selected_id, public_id, task, values=values,
            error=error.message, status_code=error.status_code, draft_result=draft_refusal_result(error))
    redirect = _web_redirect("/web/debt-goals", selected_id, msg="还债目标已保存。")
    redirect.headers["location"] += f"#goal-{result.public_id}"
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=result, next_href=redirect.headers["location"]) or redirect


@router.post("/create", response_class=HTMLResponse)
def web_debt_goal_create(
    request: Request, ledger_id: str = Form(""), name: str = Form(""),
    debt_public_ids: list[str] = Form(default=[]), idempotency_key: str = Form(""),
    draft_scope: str = Form(""), review_latest: bool = Form(False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    values = {"ledger_id": ledger_id, "name": name, "debt_public_ids": debt_public_ids, "target_date": "",
        "expected_row_version": "", "idempotency_key": idempotency_key, "draft_scope": draft_scope}
    return _save_entry(request, db, ledger_id, "", "create", values, review_latest)


@router.post("/{public_id}/links", response_class=HTMLResponse)
@router.post("/{public_id}/target-date", response_class=HTMLResponse)
def web_debt_goal_save(
    request: Request, public_id: str, ledger_id: str = Form(""), name: str = Form(""),
    debt_public_ids: list[str] = Form(default=[]), target_date: str = Form(""),
    expected_row_version: str = Form(""), idempotency_key: str = Form(""),
    draft_scope: str = Form(""), review_latest: bool = Form(False),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    values = {"ledger_id": ledger_id, "name": name, "debt_public_ids": debt_public_ids, "target_date": target_date,
        "expected_row_version": expected_row_version, "idempotency_key": idempotency_key, "draft_scope": draft_scope}
    return _save_entry(request, db, ledger_id, public_id, request.url.path.rsplit("/", 1)[1], values, review_latest)
