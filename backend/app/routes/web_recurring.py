"""Local /web recurring management page.

Routes and page assembly only. Pure presenter/form helpers live in
``_web_recurring_presenter.py``.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import MoneySign, parse_canonical_money_minor
from app.routes._web_recurring_presenter import (
    candidate_review_prefill,
    candidate_view,
    conflict_error_kwargs,
    hero_view,
    item_view,
    parse_baseline_yuan,
    parse_optional_date,
    suggest_next_expected_date,
)
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.schemas import RecurringCandidateConfirmRequest
from app.services.currency_binding_service import require_runtime_home_currency_code
from app.services.insights_service import recurring_candidates
from app.services.recurring_candidate_confirmation_service import confirm_recurring_candidate
from app.services.recurring_item_command_service import (
    create_manual_recurring_item,
    update_recurring_item,
)
from app.services.recurring_service import (
    RecurringAmountAnomaly,
    archive_recurring_item,
    list_recurring_items,
    pause_recurring_item,
    recurring_amount_anomalies,
    restore_recurring_item,
    resume_recurring_item,
)
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/recurring", tags=["web"])

_STALE_PAGE_FLASH = "页面已过期，请刷新后重新操作。"
_VALID_STATUS_FILTERS = {"active", "paused", "archived"}

# 草稿保留的 IA 分界: 客户端输入类错误 (金额/日期格式、名称缺失/超长) 保留用户
# 草稿就地修正 — 落实 ERROR_MESSAGE_MAPPING.md「缩短名称后重新保存; 已填写的其他
# 内容继续保留」, 对齐 debt_new values / 账单纠错面 form_values 的既有先例;
# 世界状态类错误 (冲突 / 归档 / OCC / 幂等 / 观察身份不可变) 不保留草稿,
# 页面刷新到服务端事实, 防止把可修正输入叠加到已变化的世界。
_DRAFT_PRESERVING_ERRORS = frozenset(
    {
        "invalid_request",
        "recurring_merchant_required",
        "recurring_merchant_too_long",
    }
)


def _conflict_kwargs(exc: AppError, *, selected_id: str, merchant: str | None = None) -> dict:
    return conflict_error_kwargs(
        exc,
        selected_id=selected_id,
        merchant=merchant,
        stale_page_flash=_STALE_PAGE_FLASH,
    )


def _load_candidate_rows(db: Session, *, selected_id: str) -> tuple[list[dict], bool]:
    try:
        return recurring_candidates(db, tenant_id=selected_id, timezone_name=None), False
    except Exception:  # noqa: BLE001 - recurring page must never 500 on insight
        logger.warning("Recurring candidate insight failed for /web/recurring.", exc_info=True)
        return [], True


def _candidate_review(
    candidate_rows: list[dict],
    *,
    review_merchant: str | None,
    currency_code: str,
    can_write: bool,
    candidates_error: bool,
) -> dict | None:
    if not review_merchant or not can_write or candidates_error:
        return None
    matched = next(
        (candidate for candidate in candidate_rows if str(candidate.get("merchant") or "") == review_merchant),
        None,
    )
    return None if matched is None else candidate_review_prefill(matched, currency_code=currency_code)


def _render_recurring(
    *,
    request: Request,
    db: Session,
    selected_id: str,
    options,
    status: str | None = None,
    flash_message: str | None = None,
    error_message: str | None = None,
    error_guidance: dict | None = None,
    review_merchant: str | None = None,
    open_edit_id: str | None = None,
    create_draft: dict | None = None,
    edit_draft: dict | None = None,
) -> HTMLResponse:
    if status and status not in _VALID_STATUS_FILTERS:
        raise AppError("recurring_status_invalid", status_code=422)
    all_items = list_recurring_items(db, tenant_id=selected_id, include_archived=True)
    # No explicit month: the service defaults to current_accounting_month
    # (Asia/Shanghai). current_month(None) here was UTC — in the 00:00-07:59
    # Beijing window on the 1st the whole page mis-binned into last month.
    anomalies = recurring_amount_anomalies(
        db,
        tenant_id=selected_id,
        items=all_items,
        timezone_name=None,
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="固定支出",
    )
    currency_code = ctx["home_currency_code"]
    # 列表按状态筛选, 默认「全部」不带归档尸体; hero 与筛选解耦, 始终全体 active。
    if status:
        visible = [item for item in all_items if item.status == status]
    else:
        visible = [item for item in all_items if item.status != "archived"]
    ctx["items"] = [
        item_view(
            item,
            anomalies.get(item.public_id) or RecurringAmountAnomaly(),
            currency_code=currency_code,
        )
        for item in visible
    ]
    # Coverage migrated from the deleted /web/stats page: candidate insight
    # failure must degrade to an inline notice, never 500 the recurring page.
    candidate_rows, candidates_error = _load_candidate_rows(db, selected_id=selected_id)
    ctx["candidates"] = [
        candidate_view(
            candidate,
            currency_code=currency_code,
            ledger_id=selected_id,
        )
        for candidate in candidate_rows
    ]
    ctx["candidates_error"] = candidates_error
    # 候选「复核采用」: 按 URL 的商家定位候选, provenance 全部来自服务端扫描。
    ctx["review"] = _candidate_review(
        candidate_rows,
        review_merchant=review_merchant,
        currency_code=currency_code,
        can_write=ctx["can_write"],
        candidates_error=candidates_error,
    )
    ctx["hero"] = hero_view(all_items, currency_code=currency_code)
    ctx["status_filter"] = status or ""
    ctx["flash_message"] = flash_message
    ctx["error_message"] = error_message
    ctx["error_guidance"] = error_guidance
    today = now_utc().astimezone(accounting_zone()).date()
    ctx["suggested_next_date"] = suggest_next_expected_date(today).isoformat()
    # 创建表单的 durable intent key: 一次渲染一把, 同一提交的重试/双击都回放它。
    ctx["create_idempotency_key"] = uuid4().hex
    ctx["open_edit_id"] = open_edit_id
    ctx.update(create_draft=create_draft, edit_draft=edit_draft)
    return templates.TemplateResponse(request=request, name="recurring.html", context=ctx)


@router.get("", response_class=HTMLResponse)
def web_recurring(
    request: Request,
    ledger_id: str | None = None,
    status: str | None = None,
    flash: str | None = None,
    review: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_recurring(
        request=request,
        db=db,
        selected_id=selected_id,
        options=options,
        status=status,
        flash_message=flash,
        review_merchant=(review or "").strip() or None,
    )


@router.post("/create", response_class=HTMLResponse)
def web_recurring_create(
    request: Request,
    ledger_id: str = Form(default=""),
    merchant: str = Form(default=""),
    baseline_amount_yuan: str = Form(default=""),
    next_expected_date: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """POST /api/recurring/items 的 Web 面: 手动 monthly 承诺 + durable replay。

    幂等键来自渲染进表单的隐藏字段 (一次渲染一把 = 一个真实表单 intent),
    双击/网络重试同一提交 → 服务端 HIT replay, 不会建第二条。
    """
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        currency_code = require_runtime_home_currency_code(db)
        amount_cents = parse_baseline_yuan(baseline_amount_yuan, currency_code=currency_code)
        expected_date = parse_optional_date(next_expected_date)
        create_manual_recurring_item(
            db,
            tenant_id=selected_id,
            idempotency_key=(idempotency_key or "").strip() or None,
            merchant=merchant,
            baseline_amount_cents=amount_cents,
            next_expected_date=expected_date,
        )
    except AppError as exc:
        db.rollback()
        kwargs = _conflict_kwargs(exc, selected_id=selected_id, merchant=merchant)
        if exc.error in _DRAFT_PRESERVING_ERRORS:
            kwargs["create_draft"] = {
                "merchant": merchant,
                "baseline_amount_yuan": baseline_amount_yuan,
                "next_expected_date": next_expected_date,
            }
        return _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            **kwargs,
        )
    return _web_redirect("/web/recurring", selected_id, flash="已加入你的固定支出。")


@router.post("/confirm-candidate", response_class=HTMLResponse)
def web_recurring_confirm_candidate(
    request: Request,
    ledger_id: str = Form(default=""),
    merchant: str = Form(...),
    amount_cents: str = Form(...),
    next_expected_date: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """候选「复核采用」的统一表单提交口: 只用 merchant + amount 定位服务端
    候选, provenance (occurrence_count / last_seen_at / confidence) 由 confirm
    service 从当前服务端扫描给出 — 本路由不接收也不转发客户端的这三个字段。
    409 conflict/archived 消费 details 给出可行动下一步。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    try:
        parsed_amount_cents = parse_canonical_money_minor(
            amount_cents,
            sign=MoneySign.POSITIVE,
            label="web_recurring.amount_cents",
        )
        payload = RecurringCandidateConfirmRequest(
            merchant=merchant,
            amount_cents=parsed_amount_cents,
            frequency="monthly",
            next_expected_date=parse_optional_date(next_expected_date),
        )
        confirm_recurring_candidate(db, tenant_id=selected_id, payload=payload)
    except AppError as exc:
        db.rollback()
        return _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            **_conflict_kwargs(exc, selected_id=selected_id, merchant=merchant),
        )
    return _web_redirect("/web/recurring", selected_id, flash="已采用建议，加入你的固定支出。")


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_recurring_edit(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    merchant: str = Form(default=""),
    baseline_amount_yuan: str = Form(default=""),
    next_expected_date: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """PATCH /api/recurring/items/{id} 的 Web 面: 统一编辑表单只提交用户预计
    (merchant / baseline / next date, 空日期 = 显式清空), 观察事实由 service 保留。
    ADR-0042: 与 API 路由同一 claim-before-OCC 握手, committed-but-unseen 的
    重放拿成功而不是 false-409。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
    try:
        currency_code = require_runtime_home_currency_code(db)
        amount_cents = parse_baseline_yuan(baseline_amount_yuan, currency_code=currency_code)
        expected_date = parse_optional_date(next_expected_date)
        update_recurring_item(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            idempotency_key=(idempotency_key or "").strip() or None,
            expected_row_version=parsed,
            merchant=merchant,
            merchant_provided=True,
            baseline_amount_cents=amount_cents,
            baseline_provided=True,
            next_expected_date=expected_date,
            next_expected_date_provided=True,
        )
    except AppError as exc:
        db.rollback()
        kwargs = _conflict_kwargs(exc, selected_id=selected_id, merchant=merchant)
        if exc.error in _DRAFT_PRESERVING_ERRORS:
            # 编辑草稿回填须保持该条目的编辑表单展开, 否则用户看不到被保留的输入。
            kwargs["open_edit_id"] = public_id
            kwargs["edit_draft"] = {
                "public_id": public_id,
                "merchant": merchant,
                "baseline_amount_yuan": baseline_amount_yuan,
                "next_expected_date": next_expected_date,
            }
        return _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            **kwargs,
        )
    return _web_redirect("/web/recurring", selected_id, flash="固定支出已保存。")


@router.post("/{public_id}/pause", response_class=HTMLResponse)
def web_recurring_pause(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
    try:
        pause_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed)
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
        raise
    return _web_redirect("/web/recurring", selected_id)


@router.post("/{public_id}/resume", response_class=HTMLResponse)
def web_recurring_resume(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
    try:
        resume_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed)
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
        raise
    return _web_redirect("/web/recurring", selected_id)


@router.post("/{public_id}/archive", response_class=HTMLResponse)
def web_recurring_archive(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    archive_recurring_item(db, tenant_id=selected_id, public_id=public_id)
    return _web_redirect("/web/recurring", selected_id)


@router.post("/{public_id}/restore", response_class=HTMLResponse)
def web_recurring_restore(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """归档项的恢复入口: 让 archived 冲突的「引导恢复」在 Web 面可行动。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
    try:
        restore_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed)
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect("/web/recurring", selected_id, flash=_STALE_PAGE_FLASH)
        raise
    return _web_redirect("/web/recurring", selected_id, flash="已恢复为活跃。")
