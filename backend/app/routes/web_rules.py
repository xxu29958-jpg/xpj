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
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _with_ledger,
    templates,
)
from app.services.classify_service import (
    apply_rules_to_pending,
    create_rule,
    delete_rule,
    list_rule_applications,
    list_rules,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    rollback_rule_application,
    update_rule,
)

router = APIRouter(prefix="/web", tags=["web"])


@router.get("/rules", response_class=HTMLResponse)
def web_rules(
    request: Request,
    ledger_id: str = "",
    preview_keyword: str = "",
    preview_category: str = "",
    apply_preview: bool = False,
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    rules = list_rules(db, selected_id)
    rule_applications = list_rule_applications(db, tenant_id=selected_id, limit=8)
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
    bulk_preview = None
    if apply_preview:
        bulk_preview = preview_apply_rules_to_pending(
            db,
            tenant_id=selected_id,
            limit=20,
        )
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["rules"] = rules
    ctx["rule_applications"] = rule_applications
    ctx["preview"] = preview
    ctx["preview_error"] = preview_error
    ctx["bulk_preview"] = bulk_preview
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
    _require_selected_ledger_write(options, selected_id)
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


@router.post("/rules/applications/{public_id}/rollback", response_class=HTMLResponse)
def web_rules_application_rollback(
    public_id: str,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    try:
        _batch, changed, skipped = rollback_rule_application(
            db,
            tenant_id=selected_id,
            public_id=public_id,
        )
        msg = f"已回滚规则应用：恢复 {changed} 条，跳过 {skipped} 条。"
    except AppError as exc:
        msg = "回滚失败：" + (exc.message or "规则应用批次不存在。")
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
    _require_selected_ledger_write(options, selected_id)
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
    _require_selected_ledger_write(options, selected_id)
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
    preview_confirmed: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options)
    _require_selected_ledger_write(options, selected_id)
    if preview_confirmed != "yes":
        msg = "请先预览影响范围，再确认应用规则。"
        return RedirectResponse(
            url=_with_ledger("/web/rules", selected_id, apply_preview="1", msg=msg),
            status_code=303,
        )
    pending_scanned, changed_count = apply_rules_to_pending(db, tenant_id=selected_id)
    msg = f"扫描了 {pending_scanned} 条待确认；改写了 {changed_count} 条分类。"
    return RedirectResponse(
        url=_with_ledger("/web/rules", selected_id, msg=msg),
        status_code=303,
    )
