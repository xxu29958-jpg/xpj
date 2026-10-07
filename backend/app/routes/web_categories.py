"""/web/categories pages (v0.4-alpha3 slice 2 / M3 / T12-T13).

Read-only category dashboard plus an uncategorized cleanup workflow.
No new schema, no migrations. Bulk-set-category delegates to the existing
``expense_service.update_expense`` so all classify side-effects stay
consistent with the API and the /web/pending bulk path.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ERROR_MESSAGES, AppError
from app.routes._web_draft_binding import browser_draft_scope
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.services.category_preference_service import (
    CategoryPreferenceView,
    delete_category_preference,
    inspect_category_preference,
    list_category_preferences,
)
from app.services.category_service import (
    DEFAULT_CATEGORIES,
    bulk_set_category,
    list_category_summary,
    list_uncategorized_pending,
    merge_categories,
)
from app.services.ledger_calendar_service import current_ledger_month
from app.services.spending_contract_service import (
    accounting_datetime_label,
    default_accounting_timezone_name,
)

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
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected_id)
    home = ctx["home_currency_code"]
    rows = list_uncategorized_pending(db, tenant_id=selected_id)
    items = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "merchant": (r.merchant or "").strip(),
                "amount_yuan": _amount_yuan(r.amount_cents, home),
                "category": r.category or "",
                "note": (r.note or "").strip(),
                "created_at": accounting_datetime_label(r.created_at),
            }
        )
    available = merge_categories([r.category for r in rows if r.category])
    ctx["uncategorized_items"] = items
    ctx["available_categories"] = available
    ctx["default_categories"] = DEFAULT_CATEGORIES
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(
        request=request, name="uncategorized.html", context=ctx
    )


@router.post("/categories/uncategorized/bulk-set")
def web_uncategorized_bulk_set(
    request: Request,
    ledger_id: str = Form(""),
    expense_ids: list[int] = Form(default=[]),
    category: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    if not expense_ids:
        return _web_redirect(
            "/web/categories/uncategorized", selected_id, msg="请勾选要修改的账单。"
        )
    try:
        changed = bulk_set_category(
            db, tenant_id=selected_id, expense_ids=expense_ids, category=category
        )
        msg = f"已将 {changed} 条账单设置为「{category.strip()}」。"
    except AppError as exc:
        msg = exc.message
    return _web_redirect("/web/categories/uncategorized", selected_id, msg=msg)
