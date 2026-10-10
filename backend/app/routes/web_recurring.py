"""Local /web recurring management page.

Routes and page assembly only. Pure presenter/form helpers live in
``_web_recurring_presenter.py``.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.money_contract import MoneySign, parse_canonical_money_minor
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
    reviewed_draft_scope,
)
from app.routes._web_recurring_presenter import (
    apply_form_draft,
    candidate_review_prefill,
    candidate_view,
    conflict_error_kwargs,
    hero_view,
    item_view,
    parse_baseline_yuan,
    parse_optional_date,
    retained_candidate_form,
    suggest_next_expected_date,
)
from app.routes._web_session_common import resolve_web_actor_account_id
from app.routes.web_common import (
    LocalOnly,
    _amount_yuan,
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
from app.routes.web_recurring_occurrences import router as occurrences_router
from app.schemas import RecurringCandidateConfirmRequest
from app.services.currency_common import normalize_currency_code, supported_currency_codes
from app.services.insights_service import recurring_candidates
from app.services.ledger_calendar_service import current_ledger_month
from app.services.recurring_candidate_confirmation_service import confirm_recurring_candidate
from app.services.recurring_history_service import recurring_item_history
from app.services.recurring_item_command_service import (
    create_manual_recurring_item,
    update_recurring_item,
)
from app.services.recurring_occurrence_query import next_due_dates
from app.services.recurring_service import (
    RecurringAmountAnomaly,
    archive_recurring_item,
    list_recurring_items,
    pause_recurring_item,
    recurring_amount_anomalies,
    recurring_monthly_total,
    restore_recurring_item,
    resume_recurring_item,
)
from app.services.spending_contract_service import accounting_zone
from app.services.time_service import now_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/recurring", tags=["web"])
router.include_router(occurrences_router)

_STALE_PAGE_FLASH = "页面已过期，请刷新后重新操作。"
_VALID_STATUS_FILTERS = {"active", "paused", "archived"}


def _lifecycle_redirect(selected_id: str, public_id: str, month: str, *,
                        status: str = "", flash: str = "", error: str = "") -> RedirectResponse:
    href = _with_ledger("/web/recurring", selected_id, month=month, status=status, flash=flash,
        error=error, edit=public_id if error else "", result_item=public_id)
    return RedirectResponse(href + "#item-" + quote(public_id, safe=""), status_code=303)


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
    can_write: bool,
    candidates_error: bool,
    submitted: dict | None = None,
) -> dict | None:
    if submitted is not None and can_write:
        return retained_candidate_form(submitted)
    if not review_merchant or not can_write or candidates_error:
        return None
    matched = next(
        (candidate for candidate in candidate_rows if str(candidate.get("merchant") or "") == review_merchant),
        None,
    )
    return None if matched is None else candidate_review_prefill(matched)


def _recurring_hero(db, *, selected_id, items, currency_code, due_dates):
    active = [item for item in items if item.status == "active"]
    total = recurring_monthly_total(db, tenant_id=selected_id, items=active,
        home_currency_code=currency_code, month=current_ledger_month(db, ledger_id=selected_id))
    return hero_view(active, currency_code=currency_code, total_cents=total, due_dates=due_dates)


def _visible_recurring_items(items, status, open_edit_id, draft):
    selected = (draft or {}).get("public_id") or open_edit_id
    if selected:
        return [item for item in items if item.public_id == selected]
    if status:
        return [item for item in items if item.status == status]
    return [item for item in items if item.status != "archived"]


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
    draft: dict | None = None,
    prepare_review: bool = False,
    draft_result: str = "",
    status_code: int = 200,
    navigation_month: str | None = None,
    candidate_draft: dict | None = None,
) -> HTMLResponse:
    if status and status not in _VALID_STATUS_FILTERS:
        raise AppError("recurring_status_invalid", status_code=422)
    all_items = list_recurring_items(db, tenant_id=selected_id, include_archived=True)
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
    ctx["currency_options"] = [currency_code, *sorted(supported_currency_codes() - {currency_code})]
    # 列表按状态筛选, 默认「全部」不带归档尸体; hero 与筛选解耦, 始终全体 active。
    visible = _visible_recurring_items(all_items, status, open_edit_id, draft)
    due_dates = next_due_dates(db, tenant_id=selected_id, items=all_items)
    ctx["items"] = [
        item_view(
            item,
            anomalies.get(item.public_id) or RecurringAmountAnomaly(),
            due_date=due_dates[item.id],
        )
        for item in visible
    ]
    # Coverage migrated from the deleted /web/stats page: candidate insight
    # failure must degrade to an inline notice, never 500 the recurring page.
    candidate_rows, candidates_error = _load_candidate_rows(db, selected_id=selected_id)
    ctx["candidates"] = [candidate_view(candidate) for candidate in candidate_rows]
    ctx["candidates_error"] = candidates_error
    # 候选「复核采用」: 按 URL 的商家定位候选, provenance 全部来自服务端扫描。
    ctx["review"] = _candidate_review(
        candidate_rows,
        review_merchant=review_merchant,
        can_write=ctx["can_write"],
        candidates_error=candidates_error,
        submitted=candidate_draft,
    )
    ctx["hero"] = _recurring_hero(db, selected_id=selected_id, items=all_items, currency_code=currency_code, due_dates=due_dates)
    ctx["status_filter"] = status or ""
    ctx["flash_message"] = flash_message
    ctx["error_message"] = error_message
    ctx["error_guidance"] = error_guidance
    today = now_utc().astimezone(accounting_zone()).date()
    ctx["suggested_next_date"] = suggest_next_expected_date(today).isoformat()
    scope = browser_draft_scope(db, request)
    if scope is not None and draft is not None and not draft.get("draft_scope"):
        draft = {**draft, "review_required": True}
    apply_form_draft(ctx, draft, prepare_review=prepare_review)
    ctx["open_edit_id"] = open_edit_id
    ctx["recurring_creation"] = draft is not None and not draft.get("public_id")
    ctx["navigation_month"] = navigation_month if navigation_month is not None else request.query_params.get("month", "")
    ctx.update(recurring_draft_scope=scope, recurring_draft_result=draft_result)
    return templates.TemplateResponse(request=request, name="recurring.html", context=ctx, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def web_recurring(
    request: Request,
    ledger_id: str | None = None,
    status: str | None = None,
    flash: str | None = None,
    error: str | None = None,
    review: str | None = None,
    edit: str | None = None,
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
        error_message=error,
        review_merchant=(review or "").strip() or None,
        open_edit_id=edit,
    )


@router.post("/create", response_class=HTMLResponse)
def web_recurring_create(
    request: Request,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    status: str = Form(default=""),
    merchant: str = Form(default=""),
    baseline_amount_yuan: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    next_expected_date: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    review_latest: str = Form(default=""),
    draft_scope: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """POST /api/recurring/items 的 Web 面: 手动 monthly 承诺 + durable replay。

    幂等键来自渲染进表单的隐藏字段 (一次渲染一把 = 一个真实表单 intent),
    双击/网络重试同一提交 → 服务端 HIT replay, 不会建第二条。
    """
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {"merchant": merchant, "baseline_amount_yuan": baseline_amount_yuan, "home_currency_code": home_currency_code,
             "next_expected_date": next_expected_date, "idempotency_key": idempotency_key, "draft_scope": draft_scope}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**draft, "ledger_id": ledger_id, "review_latest": review_latest, "month": month, "status": status}, task="添加固定支出")
    if retained is not None:
        return draft_error_response(request, AppError("session_binding_changed", "账本已切换，原稿仍保留。", status_code=409)) or retained
    _require_selected_ledger_write(options, selected_id)
    try:
        draft["draft_scope"] = reviewed_draft_scope(db, request, draft_scope, review=review_latest == "true")
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft["draft_scope"], require_session=False)
        if review_latest == "true":
            return _render_recurring(request=request, db=db, selected_id=selected_id, options=options,
                draft=draft, status=status or None, navigation_month=month, prepare_review=True, draft_result="prepared")
        currency_code = normalize_currency_code(home_currency_code)
        amount_cents = parse_baseline_yuan(baseline_amount_yuan, currency_code=currency_code)
        expected_date = parse_optional_date(next_expected_date)
        receipt = create_manual_recurring_item(
            db,
            tenant_id=selected_id,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id),
            idempotency_key=(idempotency_key or "").strip() or None,
            merchant=merchant,
            home_currency_code=currency_code,
            baseline_amount_cents=amount_cents,
            next_expected_date=expected_date,
        )
    except AppError as exc:
        db.rollback()
        return draft_error_response(request, exc) or _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            status=status or None, navigation_month=month,
            draft={**draft, "review_required": exc.error in {"idempotency_key_required", "idempotency_key_reused"}},
            draft_result=draft_refusal_result(exc),
            status_code=exc.status_code if exc.error == "session_binding_changed" else 200,
            **_conflict_kwargs(exc, selected_id=selected_id, merchant=merchant),
        )
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=receipt, next_href=_with_ledger("/web/recurring", selected_id,
        month=month, status="active", flash="已加入你的固定支出。")) or _web_redirect("/web/recurring", selected_id, month=month, status="active", flash="已加入你的固定支出。")


@router.post("/confirm-candidate", response_class=HTMLResponse)
def web_recurring_confirm_candidate(
    request: Request,
    ledger_id: str = Form(default=""),
    merchant: str = Form(...),
    amount_cents: str = Form(...),
    home_currency_code: str = Form(default=""),
    next_expected_date: str = Form(default=""),
    month: str = Form(default=""),
    status: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """候选「复核采用」的统一表单提交口: 只用 merchant + amount 定位服务端
    候选, provenance (occurrence_count / last_seen_at / confidence) 由 confirm
    service 从当前服务端扫描给出 — 本路由不接收也不转发客户端的这三个字段。
    409 conflict/archived 消费 details 给出可行动下一步。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    proposal = {"merchant": merchant, "amount_cents": amount_cents,
        "home_currency_code": home_currency_code, "next_expected_date": next_expected_date}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**proposal, "ledger_id": ledger_id, "month": month, "status": status}, task="采用固定支出建议")
    if retained is not None:
        return retained
    _require_selected_ledger_write(options, selected_id)
    try:
        parsed_amount_cents = parse_canonical_money_minor(
            amount_cents,
            sign=MoneySign.POSITIVE,
            label="web_recurring.amount_cents",
        )
        payload = RecurringCandidateConfirmRequest(
            merchant=merchant,
            home_currency_code=normalize_currency_code(home_currency_code),
            amount_cents=parsed_amount_cents,
            frequency="monthly",
            next_expected_date=parse_optional_date(next_expected_date),
        )
        item = confirm_recurring_candidate(db, tenant_id=selected_id, payload=payload,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    except AppError as exc:
        db.rollback()
        feedback = _conflict_kwargs(exc, selected_id=selected_id, merchant=merchant)
        feedback["open_edit_id"] = None
        return _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            candidate_draft=proposal,
            navigation_month=month,
            status=status or None,
            **feedback,
        )
    return _lifecycle_redirect(selected_id, item.public_id, month, status=item.status,
        flash="已采用建议，加入你的固定支出。")


@router.post("/{public_id}/edit", response_class=HTMLResponse)
def web_recurring_edit(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    status: str = Form(default=""),
    merchant: str = Form(default=""),
    baseline_amount_yuan: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    next_expected_date: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    review_latest: str = Form(default=""),
    draft_scope: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    """PATCH /api/recurring/items/{id} 的 Web 面: 统一编辑表单只提交用户预计
    (merchant / baseline / next date, 空日期 = 显式清空), 观察事实由 service 保留。
    ADR-0042: 与 API 路由同一 claim-before-OCC 握手, committed-but-unseen 的
    重放拿成功而不是 false-409。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    draft = {"public_id": public_id, "merchant": merchant, "baseline_amount_yuan": baseline_amount_yuan, "home_currency_code": home_currency_code,
             "next_expected_date": next_expected_date, "idempotency_key": idempotency_key,
             "expected_row_version": expected_row_version, "draft_scope": draft_scope}
    retained = preserve_original_ledger_form(request, db, options=options, selected=selected_id,
        fields={**draft, "ledger_id": ledger_id, "review_latest": review_latest, "month": month, "status": status}, task="修改固定支出")
    if retained is not None:
        return draft_error_response(request, AppError("session_binding_changed", "账本已切换，原稿仍保留。", status_code=409)) or retained
    parsed = parse_form_row_version_token(expected_row_version)
    _require_selected_ledger_write(options, selected_id)
    try:
        draft["draft_scope"] = reviewed_draft_scope(db, request, draft_scope, review=review_latest == "true")
        require_draft_binding(db, request, ledger_id=selected_id, draft_scope=draft["draft_scope"], require_session=False)
        if review_latest == "true":
            return _render_recurring(request=request, db=db, selected_id=selected_id, options=options,
                draft=draft, status=status or None, navigation_month=month, prepare_review=True, draft_result="prepared")
        if parsed is None:
            raise AppError("invalid_request", _STALE_PAGE_FLASH, status_code=422)
        currency_code = normalize_currency_code(home_currency_code)
        amount_cents = parse_baseline_yuan(baseline_amount_yuan, currency_code=currency_code)
        expected_date = parse_optional_date(next_expected_date)
        receipt = update_recurring_item(
            db,
            tenant_id=selected_id,
            public_id=public_id,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id),
            idempotency_key=(idempotency_key or "").strip() or None,
            expected_row_version=parsed,
            home_currency_code=currency_code,
            merchant=merchant,
            merchant_provided=True,
            baseline_amount_cents=amount_cents,
            baseline_provided=True,
            next_expected_date=expected_date,
            next_expected_date_provided=True,
        )
    except AppError as exc:
        db.rollback()
        return draft_error_response(request, exc) or _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            status=status or None, navigation_month=month,
            draft={**draft, "review_required": parsed is None or exc.error in {
                "state_conflict", "idempotency_key_required", "idempotency_key_reused",
            }},
            draft_result=draft_refusal_result(exc),
            status_code=exc.status_code if exc.error == "session_binding_changed" else 200,
            **_conflict_kwargs(exc, selected_id=selected_id, merchant=merchant),
        )
    return draft_ack_response(request, draft_scope=draft_scope, idempotency_key=idempotency_key,
        receipt=receipt, next_href=_with_ledger("/web/recurring", selected_id,
        month=month, status=status, flash="固定支出已保存。")) or _web_redirect("/web/recurring", selected_id, month=month, status=status, flash="固定支出已保存。")


@router.post("/{public_id}/pause", response_class=HTMLResponse)
def web_recurring_pause(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    month: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
    try:
        pause_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    except AppError as exc:
        if exc.error == "state_conflict":
            return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
        raise
    return _lifecycle_redirect(selected_id, public_id, month, status="paused",
        flash="固定支出已暂停，定义和已有付款关联仍保留。")


@router.post("/{public_id}/resume", response_class=HTMLResponse)
def web_recurring_resume(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    month: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
    try:
        resume_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    except AppError as exc:
        if exc.error == "state_conflict":
            return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
        raise
    return _lifecycle_redirect(selected_id, public_id, month, status="active", flash="固定支出已恢复为活跃。")


@router.post("/{public_id}/archive", response_class=HTMLResponse)
def web_recurring_archive(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    month: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    archive_recurring_item(db, tenant_id=selected_id, public_id=public_id,
        actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    return _lifecycle_redirect(selected_id, public_id, month, status="archived",
        flash="固定支出已归档，历史和已有付款关联仍保留。")


@router.post("/{public_id}/restore", response_class=HTMLResponse)
def web_recurring_restore(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    month: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """归档项的恢复入口: 让 archived 冲突的「引导恢复」在 Web 面可行动。"""
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    parsed = parse_form_row_version_token(expected_row_version)
    if parsed is None:
        return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
    try:
        restore_recurring_item(db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed,
            actor_account_id=resolve_web_actor_account_id(db, request, selected_id))
    except AppError as exc:
        if exc.error == "state_conflict":
            return _lifecycle_redirect(selected_id, public_id, month, error=_STALE_PAGE_FLASH)
        raise
    return _lifecycle_redirect(selected_id, public_id, month, status="active", flash="已恢复为活跃。")


@router.get("/{public_id}/history", response_class=HTMLResponse)
def web_recurring_history(
    request: Request, public_id: str, ledger_id: str | None = None, month: str | None = None,
    status: str = Query(default="", pattern="^(active|paused|archived)?$"), return_occurrence: bool = False,
    limit: int = Query(default=20, ge=1, le=100), before_version: int | None = Query(default=None, ge=1),
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    history = recurring_item_history(db, tenant_id=selected, public_id=public_id,
        limit=limit, before_version=before_version)
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected,
        show_month_picker=False, selected_month=month)
    ctx.update(history=history, return_month=month, status_filter=status, return_occurrence=return_occurrence,
        limit=limit, before_version=before_version, history_money=_recurring_history_money)
    return templates.TemplateResponse(request=request, name="recurring_history.html", context=ctx)


def _recurring_history_money(amount: int, currency: str | None) -> str:
    return f"{currency} {_amount_yuan(amount, currency)}" if currency else f"{amount} 最小单位（原币种未记录）"
