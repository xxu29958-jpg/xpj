"""/web/rules page routes (CRUD + preview + apply-pending).

Split from ``web_app.py`` in v0.4-alpha3 slice 2.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.models import CategoryRule
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.services.classify_service import (
    apply_rules_to_pending,
    create_rule,
    delete_rule,
    list_rules,
    preview_rule_for_pending,
    update_rule,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/rules", response_class=HTMLResponse)
def web_rules(
    request: Request,
    ledger_id: str = "",
    preview_keyword: str = "",
    preview_category: str = "",
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    rules = list_rules(db, selected_id)
    preview = None
    preview_error = None
    if preview_keyword.strip():
        try:
            matched_count, items = preview_rule_for_pending(
                db,
                tenant_id=selected_id,
                keyword=preview_keyword,
                target_category=preview_category.strip() or "其他",
                match_field="merchant",
                limit=10,
            )
            preview = {
                "matched_count": matched_count,
                "items": items,
                "keyword": preview_keyword.strip(),
                "target_category": preview_category.strip() or "其他",
            }
        except AppError as exc:
            preview_error = exc.message
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["rules"] = rules
    ctx["preview"] = preview
    ctx["preview_error"] = preview_error
    ctx["preview_keyword"] = preview_keyword
    ctx["preview_category"] = preview_category
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(request=request, name="rules.html", context=ctx)


@router.post("/rules/create", response_class=HTMLResponse)
def web_rules_create(
    keyword: str = Form(""),
    category: str = Form(""),
    priority: int = Form(100),
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    try:
        create_rule(
            db,
            tenant_id=selected_id,
            keyword=keyword,
            category=category,
            enabled=True,
            priority=priority,
        )
        msg = f"已新增规则：{keyword.strip()} → {category.strip()}"
    except AppError as exc:
        msg = "新增失败：" + (exc.message or "请检查关键词与分类。")
    return RedirectResponse(
        url=_with_ledger("/web/rules", selected_id, msg=msg),
        status_code=303,
    )


def _get_rule(db: Session, rule_id: int, tenant_id: str) -> CategoryRule | None:
    return db.scalar(
        select(CategoryRule)
        .where(CategoryRule.id == rule_id)
        .where(CategoryRule.tenant_id == tenant_id)
    )


@router.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
def web_rules_toggle(
    rule_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    rule = _get_rule(db, rule_id, selected_id)
    if rule is None:
        msg = "规则不存在。"
    else:
        update_rule(db, rule, enabled=not rule.enabled)
        msg = f"规则 [{rule.keyword}] {'已启用' if rule.enabled else '已停用'}。"
    return RedirectResponse(
        url=_with_ledger("/web/rules", selected_id, msg=msg),
        status_code=303,
    )


@router.post("/rules/{rule_id}/delete", response_class=HTMLResponse)
def web_rules_delete(
    rule_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    rule = _get_rule(db, rule_id, selected_id)
    if rule is None:
        msg = "规则不存在。"
    else:
        keyword = rule.keyword
        delete_rule(db, rule)
        msg = f"规则 [{keyword}] 已删除。"
    return RedirectResponse(
        url=_with_ledger("/web/rules", selected_id, msg=msg),
        status_code=303,
    )


@router.post("/rules/apply-pending", response_class=HTMLResponse)
def web_rules_apply_pending(
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    pending_scanned, changed_count = apply_rules_to_pending(db, tenant_id=selected_id)
    msg = f"扫描了 {pending_scanned} 条待确认；改写了 {changed_count} 条分类。"
    return RedirectResponse(
        url=_with_ledger("/web/rules", selected_id, msg=msg),
        status_code=303,
    )
