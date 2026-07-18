"""/web/categories pages (v0.4-alpha3 slice 2 / M3 / T12-T13).

Category dashboard, custom-preference maintenance, and uncategorized cleanup.
No new schema, no migrations. Bulk-set-category delegates to the existing
``expense_service.update_expense`` so all classify side-effects stay
consistent with the API and the /web/pending bulk path.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
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
    delete_category_preference,
    list_category_preferences,
)
from app.services.category_service import (
    DEFAULT_CATEGORIES,
    bulk_set_category,
    list_category_summary,
    list_uncategorized_pending,
    merge_categories,
)
from app.services.spending_contract_service import (
    current_accounting_month,
    default_accounting_timezone_name,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/categories", response_class=HTMLResponse)
def web_categories(
    request: Request,
    ledger_id: str = "",
    month: str = "",
    msg: str = "",
    error: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    timezone_name = default_accounting_timezone_name()
    target_month = month.strip() or current_accounting_month(timezone_name)
    try:
        dashboard = list_category_summary(
            db,
            tenant_id=selected_id,
            month=target_month,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        raise AppError("invalid_request", "请使用 YYYY-MM 格式的月份。", status_code=400) from exc
    rows = []
    for s in dashboard.summaries:
        rows.append(
            {
                "category": s.category,
                "confirmed_count": s.confirmed_count,
                "pending_count": s.pending_count,
                "amount_yuan": _amount_yuan(s.confirmed_amount_cents),
                "is_uncategorized": s.is_uncategorized,
            }
        )
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["categories_rows"] = rows
    ctx["target_month"] = target_month
    ctx["rule_count"] = dashboard.rule_count
    ctx["uncategorized_pending"] = dashboard.uncategorized_pending
    ctx["flash_message"] = msg
    ctx["flash_error"] = error
    ctx["category_preferences"] = list_category_preferences(
        db,
        tenant_id=selected_id,
    )
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(request=request, name="categories.html", context=ctx)


@router.post("/categories/preferences/{public_id}/delete")
def web_category_preference_delete(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
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
        return _web_redirect(
            "/web/categories",
            selected_id,
            error="页面已过期，请刷新后重新操作。",
        )
    try:
        item = delete_category_preference(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            expected_row_version=parsed,
        )
    except AppError as exc:
        message = "页面已过期，请刷新后重新操作。" if exc.error in {"state_conflict", "not_found"} else exc.message
        return _web_redirect("/web/categories", selected_id, error=message)
    return _web_redirect(
        "/web/categories",
        selected_id,
        msg=f"已从分类选项中隐藏「{item.name}」；历史流水保持不变。",
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
    rows = list_uncategorized_pending(db, tenant_id=selected_id)
    items = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "merchant": (r.merchant or "").strip(),
                "amount_yuan": _amount_yuan(r.amount_cents),
                "category": r.category or "",
                "note": (r.note or "").strip(),
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            }
        )
    available = merge_categories([r.category for r in rows if r.category])
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["uncategorized_items"] = items
    ctx["available_categories"] = available
    ctx["default_categories"] = DEFAULT_CATEGORIES
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(request=request, name="uncategorized.html", context=ctx)


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
        return _web_redirect("/web/categories/uncategorized", selected_id, msg="请勾选要修改的账单。")
    try:
        changed = bulk_set_category(db, tenant_id=selected_id, expense_ids=expense_ids, category=category)
        msg = f"已将 {changed} 条账单设置为「{category.strip()}」。"
    except AppError as exc:
        msg = exc.message
    return _web_redirect("/web/categories/uncategorized", selected_id, msg=msg)
