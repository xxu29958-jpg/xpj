"""/web/categories pages (v0.4-alpha3 slice 2 / M3 / T12-T13).

Category dashboard and the missing-category task, using the pending bulk command owner.
"""

from __future__ import annotations

import json
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_reporting import retain_handled_error
from app.errors import ERROR_MESSAGES, AppError
from app.routes._web_bulk_snapshot import parse_bulk_snapshot
from app.routes._web_draft_binding import browser_draft_scope, require_draft_binding
from app.routes._web_expense_return_context import flow_href
from app.routes._web_pending_bulk_response import format_bulk_message
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _expense_view,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    preserve_original_ledger_form,
    templates,
)
from app.services.category_preference_service import (
    CategoryPreferenceView,
    delete_category_preference,
    inspect_category_preference,
    list_category_preferences,
)
from app.services.category_service import (
    list_category_summary,
    list_ledger_category_options,
    list_uncategorized_pending,
)
from app.services.expense_service import list_expenses_by_ids
from app.services.ledger_calendar_service import current_ledger_month
from app.services.pending_review_bulk_service import BulkResult, apply_review_bulk
from app.services.spending_contract_service import default_accounting_timezone_name

router = APIRouter(prefix="/web", tags=["web"])


def _render_categories(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    month: str = "",
    msg: str = "",
    category_error: str = "",
    category_error_public_id: str = "",
    category_references: list[dict[str, str]] | None = None,
    inspected_category: CategoryPreferenceView | None = None,
    inspection_failed: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    timezone_name = default_accounting_timezone_name()
    target_month = month.strip() or current_ledger_month(db, ledger_id=selected_id)
    try:
        dashboard = list_category_summary(
            db,
            tenant_id=selected_id,
            month=target_month,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        raise AppError(
            "invalid_request",
            "请使用 YYYY-MM 格式的月份。",
            status_code=400,
        ) from exc
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
    )
    home = ctx["home_currency_code"]
    selected_category = category_error_public_id or (inspected_category.public_id if inspected_category else "")
    reference_links = []
    for reference in category_references or []:
        identifier = quote(reference["id"], safe="")
        origin = {"ledger_id": selected_id, "return_category": selected_category, "return_month": target_month}
        query = urlencode(origin)
        if reference["kind"] == "rule":
            href = f"/web/rules/{identifier}/edit?{query}"
        elif reference["kind"] == "budget":
            href = "/web/budgets?" + urlencode({"ledger_id": selected_id, "month": reference["id"],
                "return_category": selected_category, "return_month": target_month})
        elif reference["kind"] == "goal":
            href = f"/web/goals/{identifier}/edit?{query}"
        else:
            continue
        reference_links.append({"label": reference["label"], "href": href})
    ctx.update(
        categories_rows=[
            {
                "category": summary.category,
                "confirmed_count": summary.confirmed_count,
                "pending_count": summary.pending_count,
                "amount_yuan": _amount_yuan(
                    summary.confirmed_amount_cents,
                    home,
                ),
                "is_uncategorized": summary.is_uncategorized,
            }
            for summary in dashboard.summaries
        ],
        target_month=target_month,
        rule_count=dashboard.rule_count,
        uncategorized_pending=dashboard.uncategorized_pending,
        other_pending=sum(row.pending_count for row in dashboard.summaries if row.category == "其他"),
        category_preferences=list_category_preferences(
            db,
            tenant_id=selected_id,
        ),
        flash_message=msg,
        category_error=category_error,
        category_error_public_id=category_error_public_id,
        category_reference_links=reference_links,
        inspected_category=inspected_category,
        inspection_failed=inspection_failed,
        reference_draft_scope=browser_draft_scope(db, request),
        q="?ledger_id=" + selected_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="categories.html",
        context=ctx,
        status_code=status_code,
    )


@router.get("/categories", response_class=HTMLResponse)
def web_categories(
    request: Request,
    ledger_id: str = "",
    month: str = "",
    msg: str = "",
    inspect: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    inspected = None
    references = None
    if inspect:
        try:
            inspected, references = inspect_category_preference(db, tenant_id=selected_id, public_id=inspect)
        except AppError as exc:
            return _render_categories(request, db, options=options, selected_id=selected_id, month=month,
                category_error=exc.message, category_error_public_id=inspect, inspection_failed=True,
                status_code=exc.status_code)
    return _render_categories(
        request,
        db,
        options=options,
        selected_id=selected_id,
        month=month,
        msg=msg,
        inspected_category=inspected,
        category_references=references,
    )


@router.post(
    "/categories/preferences/{public_id}/delete",
    response_class=HTMLResponse,
)
def web_category_preference_delete(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    expected_row_version: str = Form(""),
    month: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id or None,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _render_categories(
            request,
            db,
            options=options,
            selected_id=selected_id,
            month=month,
            category_error="页面已过期，请使用当前分类状态重试。",
            category_error_public_id=public_id,
            inspection_failed=True,
            status_code=422,
        )
    try:
        removed = delete_category_preference(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
        )
    except AppError as exc:
        message = (
            "分类已在其它端被修改，请刷新后重试。"
            if exc.error == "state_conflict"
            and exc.message == ERROR_MESSAGES["state_conflict"]
            else exc.message
        )
        return _render_categories(
            request,
            db,
            options=options,
            selected_id=selected_id,
            month=month,
            category_error=message,
            category_error_public_id=public_id,
            category_references=(exc.details or {}).get("category_references", []),
            inspection_failed=True,
            status_code=422,
        )
    return _web_redirect(
        "/web/categories",
        selected_id,
        month=month,
        msg=(
            f"已从可选分类移除「{removed.name}」；历史流水不会改写，"
            "需要时可从回收站恢复。"
        ),
    )


@router.get("/categories/uncategorized", response_class=HTMLResponse)
def web_uncategorized(
    request: Request,
    ledger_id: str = "",
    msg: str = "",
    filter: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    return _render_uncategorized(request, db, options=options, selected_id=selected_id, filter=filter, message=msg)


def _render_uncategorized(request, db, *, options, selected_id: str, filter: str = "",
    message: str = "", category: str = "", snapshots: dict[int, int] | None = None,
    result: BulkResult | None = None, error: AppError | None = None) -> HTMLResponse:
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    include_other = filter == "including_other"
    rows = list_uncategorized_pending(db, tenant_id=selected_id, include_other=include_other)
    successful = set(result.success_ids) if result else set()
    remaining = {identity: version for identity, version in (snapshots or {}).items() if identity not in successful}
    # Failed selections remain visible even when a later edit moved them out of this filter.
    extra = list_expenses_by_ids(db, tenant_id=selected_id, expense_ids=list(remaining.keys() | successful))
    combined = {row.id: row for row in rows}
    combined.update((row.id, row) for row in extra)
    items, updated = [], []
    for row in combined.values():
        view = _expense_view(row, presentation_currency_code=ctx["home_currency_code"])
        view.update(selected=row.id in remaining, snapshot_version=remaining.get(row.id, row.row_version),
            detail_href=flow_href(f"/web/expenses/{row.id}/edit", ledger_id=selected_id,
                return_to="uncategorized", return_filter=filter))
        (updated if row.id in successful else items).append(view)
    scope = browser_draft_scope(db, request)
    categories = list_ledger_category_options(db, tenant_id=selected_id)
    primary = [name for name in ("购物", "餐饮", "交通", "住房", "医疗", "其他") if name in categories]
    more = [name for name in categories if name not in primary]
    if category and category not in categories:
        more.append(category)
    ctx.update(uncategorized_items=items, updated_items=updated, primary_categories=primary, more_categories=more,
        category=category, filter="including_other" if include_other else "", flash_message=message,
        flash_error=error is not None or bool(result and result.skipped_reasons),
        draft_scope=json.dumps(scope) if scope else "", q="?ledger_id=" + quote(selected_id, safe=""))
    return templates.TemplateResponse(request=request, name="uncategorized.html", context=ctx,
        status_code=error.status_code if error else 200, headers={"Cache-Control": "no-store"})


@router.post("/categories/uncategorized/bulk-set")
def web_uncategorized_bulk_set(
    request: Request,
    ledger_id: str = Form(""),
    expense_ids: list[int] = Form(default=[]),
    expected_row_version: list[str] = Form(default=[]),
    expense_snapshot: list[str] = Form(default=[]),
    category: str = Form(""),
    filter: str = Form(""),
    draft_scope: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    fields = {"ledger_id": ledger_id, "category": category, "filter": filter, "draft_scope": draft_scope,
        "expense_ids": expense_ids, "expected_row_version": expected_row_version, "expense_snapshot": expense_snapshot}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields=fields, task="给所选账单补分类")
    if retained is not None:
        return retained
    try:
        _require_selected_ledger_write(options, selected_id)
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft_scope, require_session=False)
    except AppError as exc:
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id,
            fields=fields, task="给所选账单补分类", error=exc)
    snapshot = parse_bulk_snapshot(expense_ids, expected_row_version, expense_snapshot)
    if snapshot is None:
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id, fields=fields,
            task="给所选账单补分类", error=AppError("state_conflict", "原选择的版本无法确认，请重新打开账单核对。", status_code=409))
    identities, versions = snapshot
    try:
        if not identities:
            raise AppError("invalid_request", "请勾选要修改的账单。", status_code=422)
        result = apply_review_bulk(db, tenant_id=selected_id, action="set_category", expense_ids=identities,
            expected_row_version_by_id=versions, category=category)
    except AppError as exc:
        return _render_uncategorized(request, db, options=options, selected_id=selected_id, filter=filter,
            category=category, snapshots=versions, message=exc.message, error=exc)
    except SQLAlchemyError as exc:
        retain_handled_error(request, exc)
        db.rollback()
        return preserve_original_ledger_form(request, db, options=options, selected=selected_id, fields=fields,
            task="核对本次补分类结果", error=AppError("internal_error",
                "暂时无法核实全部结果。原选择和分类仍保留，请恢复连接后核实；已经保存的分类不会自动撤销。", status_code=503))
    return _render_uncategorized(request, db, options=options, selected_id=selected_id, filter=filter,
        category=category, snapshots=versions, result=result, message=format_bulk_message("set_category", result))
