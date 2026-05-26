"""/web/rules page routes (CRUD + preview + apply-pending).

Split from ``web_app.py`` in v0.4-alpha3 slice 2.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.services.classify_service import (
    apply_rules_to_confirmed,
    apply_rules_to_pending,
    create_rule,
    delete_rule,
    find_rule_for_tenant,
    list_rule_applications,
    list_rules,
    preview_apply_rules_to_confirmed,
    preview_apply_rules_to_pending,
    preview_rule_for_pending,
    rollback_rule_application,
    update_rule,
    validate_rule_application_preview,
)

if TYPE_CHECKING:
    from app.models import CategoryRule

router = APIRouter(prefix="/web", tags=["web"])


def _parse_optional_amount_cents(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise AppError("invalid_request", "金额条件不是合法数字。", status_code=422) from exc
    cents = int((amount * Decimal("100")).to_integral_value())
    if cents < 0:
        raise AppError("invalid_request", "金额条件不能为负数。", status_code=422)
    return cents


@router.get("/rules", response_class=HTMLResponse)
def web_rules(
    request: Request,
    ledger_id: str = "",
    preview_keyword: str = "",
    preview_category: str = "",
    apply_preview: bool = False,
    confirmed_preview: bool = False,
    msg: str = "",
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
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
    confirmed_bulk_preview = None
    if confirmed_preview:
        confirmed_bulk_preview = preview_apply_rules_to_confirmed(
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
    ctx["confirmed_bulk_preview"] = confirmed_bulk_preview
    ctx["preview_keyword"] = preview_keyword
    ctx["preview_category"] = preview_category
    ctx["flash_message"] = msg
    ctx["q"] = "?ledger_id=" + selected_id
    return templates.TemplateResponse(request=request, name="rules.html", context=ctx)


@router.post("/rules/create", response_class=HTMLResponse)
def web_rules_create(
    request: Request,
    keyword: str = Form(""),
    category: str = Form(""),
    priority: int = Form(100),
    amount_min_yuan: str = Form(""),
    amount_max_yuan: str = Form(""),
    source_contains: str = Form(""),
    tag_contains: str = Form(""),
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        create_rule(
            db,
            tenant_id=selected_id,
            keyword=keyword,
            category=category,
            enabled=True,
            priority=priority,
            amount_min_cents=_parse_optional_amount_cents(amount_min_yuan),
            amount_max_cents=_parse_optional_amount_cents(amount_max_yuan),
            source_contains=source_contains,
            tag_contains=tag_contains,
        )
        msg = f"已新增规则：{keyword.strip()} → {category.strip()}"
    except AppError as exc:
        msg = "新增失败：" + (exc.message or "请检查关键词与分类。")
    return _web_redirect("/web/rules", selected_id, msg=msg)


@router.post("/rules/applications/{public_id}/rollback", response_class=HTMLResponse)
def web_rules_application_rollback(
    request: Request,
    public_id: str,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
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
    return _web_redirect("/web/rules", selected_id, msg=msg)


def _get_rule(db: Session, rule_id: int, tenant_id: str) -> CategoryRule | None:
    return find_rule_for_tenant(db, tenant_id=tenant_id, rule_id=rule_id)


@router.post("/rules/{rule_id}/toggle", response_class=HTMLResponse)
def web_rules_toggle(
    request: Request,
    rule_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    rule = _get_rule(db, rule_id, selected_id)
    if rule is None:
        msg = "规则不存在。"
    else:
        # /web is loopback owner-console flow; same-request fetch-then-
        # write has no race window under SQLite's single-writer guarantee,
        # so we pass the rule's current updated_at as the expected value.
        # PR-2 (expense PATCH) will wire a hidden form field for cross-
        # request concurrency on user-facing /web pages.
        updated_rule = update_rule(
            db, rule, expected_updated_at=rule.updated_at, enabled=not rule.enabled
        )
        msg = f"规则 [{updated_rule.keyword}] {'已启用' if updated_rule.enabled else '已停用'}。"
    return _web_redirect("/web/rules", selected_id, msg=msg)


@router.post("/rules/{rule_id}/delete", response_class=HTMLResponse)
def web_rules_delete(
    request: Request,
    rule_id: int,
    ledger_id: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    rule = _get_rule(db, rule_id, selected_id)
    if rule is None:
        msg = "规则不存在。"
    else:
        keyword = rule.keyword
        # See web_rules_toggle: loopback flow uses the rule's own
        # updated_at as expected (no race window).
        delete_rule(db, rule, expected_updated_at=rule.updated_at)
        msg = f"规则 [{keyword}] 已删除。"
    return _web_redirect("/web/rules", selected_id, msg=msg)


@router.post("/rules/apply-pending", response_class=HTMLResponse)
def web_rules_apply_pending(
    request: Request,
    ledger_id: str = Form(""),
    preview_confirmed: str = Form(""),
    preview_token: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    if preview_confirmed != "yes":
        msg = "请先预览影响范围，再确认应用规则。"
        return _web_redirect("/web/rules", selected_id, apply_preview="1", msg=msg)
    try:
        current_preview = validate_rule_application_preview(
            db,
            tenant_id=selected_id,
            status="pending",
            preview_token=preview_token,
        )
    except AppError:
        current_preview = None
    if not preview_token or not current_preview or current_preview["preview_token"] != preview_token:
        msg = "待确认账单预览已过期，请重新预览后再确认应用。"
        return _web_redirect("/web/rules", selected_id, apply_preview="1", msg=msg)
    pending_scanned, changed_count, limited = apply_rules_to_pending(db, tenant_id=selected_id)
    suffix = " 还有未扫描账单，可再次预览并应用。" if limited else ""
    msg = f"扫描了 {pending_scanned} 条待确认；改写了 {changed_count} 条分类。{suffix}"
    return _web_redirect("/web/rules", selected_id, msg=msg)


@router.post("/rules/apply-confirmed", response_class=HTMLResponse)
def web_rules_apply_confirmed(
    request: Request,
    ledger_id: str = Form(""),
    preview_confirmed: str = Form(""),
    preview_token: str = Form(""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    if preview_confirmed != "yes":
        msg = "历史账单修改必须先预览影响范围，再确认应用。"
        return _web_redirect("/web/rules", selected_id, confirmed_preview="1", msg=msg)
    try:
        current_preview = validate_rule_application_preview(
            db,
            tenant_id=selected_id,
            status="confirmed",
            preview_token=preview_token,
        )
    except AppError:
        current_preview = None
    if not preview_token or not current_preview or current_preview["preview_token"] != preview_token:
        msg = "历史账单预览已过期，请重新预览后再确认应用。"
        return _web_redirect("/web/rules", selected_id, confirmed_preview="1", msg=msg)
    confirmed_scanned, changed_count, limited = apply_rules_to_confirmed(db, tenant_id=selected_id)
    suffix = " 还有未扫描账单，可再次预览并应用。" if limited else ""
    msg = f"扫描了 {confirmed_scanned} 条已确认；改写了 {changed_count} 条分类。{suffix}"
    return _web_redirect("/web/rules", selected_id, msg=msg)
