"""/web/duplicates side-by-side review (v0.4-alpha3 slice 2 / PR18).

Lists every pending expense currently flagged as a suspected duplicate
together with its referenced comparison row, so the user can resolve the pair
in a single click. Either row may still be pending or already confirmed:

* **不是重复，保留两条** — calls ``mark_expense_not_duplicate`` (records the
  ignore pair so it never re-fires for the same kind).
* **忽略当前记录** — rejects the suspected row (restorable).
* **忽略参考记录** — rejects a still-pending referenced row, then clears the
  suspected flag on the kept row. Confirmed references remain immutable here
  and direct the user to correction/reversal semantics instead.

All actions stay loopback-only via ``LocalOnly`` and respect ledger
isolation via ``selected_id``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    require_draft_binding,
)
from app.routes._web_expense_confirmation import render_confirmation_task
from app.routes._web_expense_edit_command import expense_edit_form_values
from app.routes._web_expense_edit_form import WebExpenseEditForm, web_expense_edit_form
from app.routes._web_expense_helpers import (
    confirm_reject_error,
    drawer_fragment_ok,
    web_edit_context,
)
from app.routes._web_expense_return_context import flow_href, return_context_params
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.expense_review_command_service import (
    reject_duplicate_original_keep_current,
    submit_expense_duplicate_decision,
    submit_expense_rejection,
)
from app.services.expense_service import (
    get_expense,
    list_duplicate_expenses,
    list_expenses_by_ids,
)

if TYPE_CHECKING:
    from app.models import Expense

router = APIRouter(prefix="/web", tags=["web"])


# 218-D S4 (移植自产品矿): 重复对照页的行状态 chip 与判定原因文案由路由 glue
# 提供, 模板只读 status_label/status_tone/reason_label, 不拼原始 status 串。
_EXPENSE_STATUS_UI = {
    "pending": ("待确认", "warning"),
    "confirmed": ("已入账", "success"),
    "rejected": ("已忽略", ""),
}


def _duplicate_expense_view(
    expense: Expense,
    *,
    presentation_currency_code: str,
) -> dict:
    view = _expense_view(
        expense,
        presentation_currency_code=presentation_currency_code,
    )
    status_label, status_tone = _EXPENSE_STATUS_UI.get(
        str(view.get("status") or ""),
        ("状态待确认", ""),
    )
    view["status_label"] = status_label
    view["status_tone"] = status_tone
    view["reject_idempotency_key"] = str(uuid4())
    view["keep_idempotency_key"] = str(uuid4())
    return view


def _duplicate_evidence(reason: str) -> tuple[str, str, str]:
    """Map persisted detector evidence to honest user-facing labels.

    The detector stores a reason, not a calibrated probability.  Do not turn
    these categorical rules into invented similarity percentages.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        return "系统未提供判定原因", "待人工核对", ""
    if "感知" in cleaned and "hash" in cleaned:
        return "两张图片内容高度相似", "图片近似", "warning"
    if "hash" in cleaned or "完全一致" in cleaned:
        return "两张图片完全一致", "图片一致", "danger"
    if "金额" in cleaned and "时间" in cleaned:
        return "金额、商家和消费时间接近", "字段接近", "warning"
    return "系统未提供判定原因", "待人工核对", ""


def _load_pair(db: Session, *, tenant_id: str, expense_id: int) -> tuple[Expense, Expense | None]:
    expense = get_expense(db, expense_id, tenant_id)
    other: Expense | None = None
    if expense.duplicate_of_id is not None:
        others = list_expenses_by_ids(
            db, tenant_id=tenant_id, expense_ids=[expense.duplicate_of_id]
        )
        other = others[0] if others else None
    return expense, other


@router.get("/duplicates", response_class=HTMLResponse)
def web_duplicates(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    flash_type: str = "",
    focus: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    rows = list_duplicate_expenses(db, selected_id)
    # Single batched query for every referenced original; pair-build loop
    # below does in-memory lookup. No N+1 over duplicate rows.
    original_ids = sorted({row.duplicate_of_id for row in rows if row.duplicate_of_id is not None})
    originals_by_id = {
        e.id: e
        for e in list_expenses_by_ids(db, tenant_id=selected_id, expense_ids=original_ids)
    }
    home = require_runtime_home_currency_code(db)
    pairs = []
    for row in rows:
        original = (
            originals_by_id.get(row.duplicate_of_id)
            if row.duplicate_of_id is not None
            else None
        )
        reason = row.duplicate_reason or ""
        reason_label, evidence_label, evidence_tone = _duplicate_evidence(reason)
        current_view = _duplicate_expense_view(
            row,
            presentation_currency_code=home,
        )
        original_view = (
            _duplicate_expense_view(
                original,
                presentation_currency_code=home,
            )
            if original is not None
            else None
        )
        diff_fields: list[str] = []
        if original_view:
            if current_view.get("merchant") != original_view.get("merchant"):
                diff_fields.append("merchant")
            if any(current_view.get(key) != original_view.get(key)
                for key in ("original_currency_code", "original_amount_minor", "amount_cents")):
                diff_fields.append("amount")
            if current_view.get("expense_time") != original_view.get("expense_time"):
                diff_fields.append("time")
        for view in (current_view, original_view):
            if view:
                view["detail_href"] = flow_href(f"/web/expenses/{view['id']}/edit", ledger_id=selected_id,
                    return_to="duplicates", return_duplicate_expense_id=str(row.id))
        pairs.append(
            {
                "current": current_view,
                "original": original_view,
                "reason_label": reason_label,
                "evidence_label": evidence_label,
                "evidence_tone": evidence_tone,
                "diff_fields": diff_fields,
            }
        )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="疑似重复",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["duplicate_pairs"] = pairs
    ctx["duplicate_focus"] = parse_form_row_version_token(focus)
    scope = browser_draft_scope(db, request)
    ctx["duplicate_draft_scope"] = json.dumps(scope) if scope else ""
    ctx["flash_message"] = msg
    # S4-R1: 与 pending 同族 — 只有 error/success 两个合法值, 其余回落默认
    # info 样式, 避免查询参数驱动任意类名。
    ctx["flash_type"] = flash_type if flash_type in ("success", "error") else ""
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="duplicates.html", context=ctx
    )


_STALE_DUPLICATE_MSG = "账单已在其它端被修改，请刷新后重新操作。"


@router.post("/duplicates/{expense_id}/keep")
def web_duplicate_keep(
    request: Request,
    expense_id: int,
    form: WebExpenseEditForm = Depends(web_expense_edit_form),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, form.ledger_id or None, options, request=request)
    values = {**expense_edit_form_values(form), "draft_scope": form.draft_scope, "draft_ref": form.draft_ref,
        "command_action": form.command_action, "keep_idempotency_key": form.keep_idempotency_key,
        "reject_idempotency_key": form.reject_idempotency_key}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**values, **form.return_context.as_kwargs(), "ledger_id": form.ledger_id,
            "save_before_confirm": "1" if form.save_before_confirm else "0", "fragment": str(form.fragment)},
        task="保留原非重复决定与核对填写")
    if retained is not None:
        return retained
    error_msg: str | None = None
    try:
        _require_selected_ledger_write(options, selected_id)
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=form.draft_scope, require_session=False)
        if form.review_latest:
            return render_confirmation_task(request, db, options=options, ledger_id=selected_id, expense_id=expense_id,
                form=replace(form, command_action="keep"), result="prepared")
        parsed = parse_form_row_version_token(form.expected_row_version)
        if parsed is None:
            raise AppError("state_conflict", _STALE_DUPLICATE_MSG, status_code=422)
        submit_expense_duplicate_decision(db, tenant_id=selected_id, expense_id=expense_id,
            expected_row_version=parsed, request_expected_row_version=parsed, idempotency_key=form.keep_idempotency_key)
    except AppError as exc:
        db.rollback()
        if response := draft_error_response(request, exc):
            return response
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        if form.fragment or form.save_before_confirm:
            return confirm_reject_error(db, request, options, selected_id, expense_id, error_msg, form.fragment,
                status_code=exc.status_code, form_values=values, return_context=form.return_context)
        if exc.status_code in {401, 403}:
            raise
    if error_msg is None:
        next_href = flow_href(f"/web/expenses/{expense_id}/edit", ledger_id=selected_id, **form.return_context.as_kwargs())
        response = draft_ack_response(request, draft_scope=form.draft_scope, idempotency_key=form.keep_idempotency_key,
            receipt={"operation": "mark_not_duplicate", "expense_id": expense_id, "accepted": True, "decision_key": form.keep_idempotency_key},
            next_href=next_href + "&confirmation_task=1#expensereview-edit-" + quote(form.draft_ref, safe=""))
        if response is not None:
            return response
    if form.fragment and error_msg is None:
        return drawer_fragment_ok("keep")
    if form.save_before_confirm:
        ctx = web_edit_context(db, request, options, selected_id, expense_id,
            form_values=values, return_context=form.return_context)
        ctx.update(message="这次非重复决定已保存。原填写仍保留，请继续核对当前记录。", expense_review_task=True)
        return templates.TemplateResponse(request=request, name="edit.html", context=ctx)
    return _web_redirect("/web/duplicates", selected_id, msg=error_msg or "这次非重复决定已保存。",
        flash_type="error" if error_msg is not None else "success",
        focus=str(expense_id) if error_msg else return_context_params("duplicates",
            return_duplicate_expense_id=form.return_context.return_duplicate_expense_id).get("focus", ""))


@router.post("/duplicates/{expense_id}/reject-current")
def web_duplicate_reject_current(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    idempotency_key: str = Form(""),
    draft_scope: str = Form(""),
    return_duplicate_expense_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {"ledger_id": ledger_id, "expense_id": str(expense_id), "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key, "draft_scope": draft_scope,
        "return_duplicate_expense_id": return_duplicate_expense_id}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=fields, task="继续原相似账单判定")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft_scope, require_session=False)
    except AppError as exc:
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="原相似账单判定仍保留", error=exc)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect(
            "/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG, flash_type="error", focus=str(expense_id)
        )
    error_msg: str | None = None
    try:
        submit_expense_rejection(
            db,
            operation="reject_expense",
            expense_id=expense_id,
            tenant_id=selected_id,
            expected_row_version=parsed,
            request_expected_row_version=parsed,
            idempotency_key=idempotency_key,
            actor_account_id=None,
        )
        msg = "已忽略当前记录。"
    except AppError as exc:
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        msg = error_msg
    return _web_redirect(
        "/web/duplicates",
        selected_id,
        msg=msg,
        flash_type="error" if error_msg is not None else "success",
        focus=str(expense_id) if error_msg else return_context_params("duplicates",
            return_duplicate_expense_id=return_duplicate_expense_id).get("focus", ""),
    )


@router.post("/duplicates/{expense_id}/reject-original")
def web_duplicate_reject_original(
    request: Request,
    expense_id: int,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    original_expense_id: str = Form(""),
    expected_original_row_version: str = Form(""),
    draft_scope: str = Form(""),
    return_duplicate_expense_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {"ledger_id": ledger_id, "expense_id": str(expense_id), "expected_row_version": expected_row_version,
        "original_expense_id": original_expense_id, "expected_original_row_version": expected_original_row_version,
        "draft_scope": draft_scope, "return_duplicate_expense_id": return_duplicate_expense_id}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=fields, task="继续原两笔账单的判定")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft_scope, require_session=False)
    except AppError as exc:
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="原两笔账单的判定仍保留", error=exc)
    parsed = parse_form_row_version_token(expected_row_version)
    parsed_original_id = parse_form_row_version_token(original_expense_id)
    parsed_original_version = parse_form_row_version_token(expected_original_row_version)
    if parsed is None or parsed_original_id is None or parsed_original_version is None:
        return _web_redirect(
            "/web/duplicates", selected_id, msg=_STALE_DUPLICATE_MSG, flash_type="error", focus=str(expense_id)
        )
    msg = "已忽略参考记录，并保留当前记录。"
    error_msg: str | None = None
    try:
        reject_duplicate_original_keep_current(
            db,
            current_expense_id=expense_id,
            original_expense_id=parsed_original_id,
            tenant_id=selected_id,
            expected_row_version=parsed,
            expected_original_row_version=parsed_original_version,
        )
    except AppError as exc:
        error_msg = _STALE_DUPLICATE_MSG if exc.error == "state_conflict" else exc.message
        msg = error_msg
    return _web_redirect(
        "/web/duplicates",
        selected_id,
        msg=msg,
        flash_type="error" if error_msg is not None else "success",
        focus=str(expense_id) if error_msg else return_context_params("duplicates",
            return_duplicate_expense_id=return_duplicate_expense_id).get("focus", ""),
    )
