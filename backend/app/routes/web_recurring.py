"""Local /web recurring management page."""

from __future__ import annotations

import logging

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
from app.schemas import RecurringCandidateConfirmRequest
from app.services.insights_service import recurring_candidates
from app.services.recurring_service import (
    RecurringAmountAnomaly,
    archive_recurring_item,
    confirm_recurring_candidate,
    list_recurring_items,
    pause_recurring_item,
    recurring_amount_anomalies,
    resume_recurring_item,
)
from app.services.time_service import to_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/recurring", tags=["web"])


def _status_label(status: str) -> str:
    return {
        "active": "活跃",
        "paused": "暂停",
        "archived": "归档",
    }.get(status, status)


def _anomaly_label(status: str) -> str:
    return {
        "higher_than_average": "本月偏高",
        "none": "正常",
    }.get(status, status)


def _item_view(item, anomaly) -> dict:
    return {
        "public_id": item.public_id,
        "merchant": item.merchant_name,
        "frequency": "每月" if item.frequency == "monthly" else item.frequency,
        "baseline_amount_yuan": _amount_yuan(item.baseline_amount_cents),
        "last_amount_yuan": _amount_yuan(item.last_amount_cents),
        "occurrence_count": item.occurrence_count,
        "last_seen_at": to_iso(item.last_seen_at),
        "next_expected_date": item.next_expected_date.isoformat() if item.next_expected_date else "",
        "status": item.status,
        "status_label": _status_label(item.status),
        # ADR-0041: OCC token (row_version) for the hidden pause/resume form
        # field. Without it parse_form_row_version_token sees "" → the user
        # always hits the "页面已过期" redirect and can never toggle from this page.
        "row_version": item.row_version,
        "updated_at": to_iso(item.updated_at),
        "confidence": item.confidence or "",
        "anomaly_status": anomaly.anomaly_status,
        "anomaly_label": _anomaly_label(anomaly.anomaly_status),
        "current_month_amount_yuan": _amount_yuan(anomaly.current_month_amount_cents),
        "historical_average_amount_yuan": _amount_yuan(anomaly.historical_average_amount_cents),
        "amount_delta_percent": anomaly.amount_delta_percent,
    }


def _candidate_view(candidate: dict) -> dict:
    return {
        "merchant": str(candidate.get("merchant") or ""),
        "amount_cents": int(candidate.get("amount_cents") or 0),
        "amount_yuan": _amount_yuan(int(candidate.get("amount_cents") or 0)),
        "occurrence_count": int(candidate.get("occurrence_count") or 0),
        "last_seen_at": to_iso(candidate.get("last_seen_at")),
        "confidence": str(candidate.get("confidence") or ""),
        "reason": str(candidate.get("reason") or ""),
    }


def _render_recurring(
    *,
    request: Request,
    db: Session,
    selected_id: str,
    options,
    status: str | None = None,
    flash_message: str | None = None,
) -> HTMLResponse:
    items = list_recurring_items(db, tenant_id=selected_id, status=status or None, include_archived=True)
    # No explicit month: the service defaults to current_accounting_month
    # (Asia/Shanghai). current_month(None) here was UTC — in the 00:00-07:59
    # Beijing window on the 1st the whole page mis-binned into last month.
    anomalies = recurring_amount_anomalies(
        db,
        tenant_id=selected_id,
        items=items,
        timezone_name=None,
    )
    ctx = _base_ctx(request, options=options, selected_ledger_id=selected_id)
    ctx["items"] = [
        _item_view(item, anomalies.get(item.public_id) or RecurringAmountAnomaly())
        for item in items
    ]
    # Coverage migrated from the deleted /web/stats page: candidate insight
    # failure must degrade to an inline notice, never 500 the recurring page.
    candidates_error = False
    try:
        candidate_rows = recurring_candidates(db, tenant_id=selected_id, timezone_name=None)
    except Exception:  # noqa: BLE001 - recurring page must never 500 on insight
        logger.warning("Recurring candidate insight failed for /web/recurring.", exc_info=True)
        candidate_rows = []
        candidates_error = True
    ctx["candidates"] = [_candidate_view(candidate) for candidate in candidate_rows]
    ctx["candidates_error"] = candidates_error
    ctx["status_filter"] = status or ""
    ctx["flash_message"] = flash_message
    return templates.TemplateResponse(request=request, name="recurring.html", context=ctx)


@router.get("", response_class=HTMLResponse)
def web_recurring(
    request: Request,
    ledger_id: str | None = None,
    status: str | None = None,
    flash: str | None = None,
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
    )


@router.post("/confirm-candidate", response_class=HTMLResponse)
def web_recurring_confirm_candidate(
    request: Request,
    ledger_id: str = Form(default=""),
    merchant: str = Form(...),
    amount_cents: int = Form(...),
    occurrence_count: int = Form(default=0),
    last_seen_at: str = Form(default=""),
    confidence: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
):
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    _require_selected_ledger_write(options, selected_id)
    payload = RecurringCandidateConfirmRequest(
        merchant=merchant,
        amount_cents=amount_cents,
        occurrence_count=occurrence_count,
        last_seen_at=last_seen_at or None,
        confidence=confidence or None,
        frequency="monthly",
    )
    try:
        confirm_recurring_candidate(db, tenant_id=selected_id, payload=payload)
    except AppError as exc:
        return _render_recurring(
            request=request,
            db=db,
            selected_id=selected_id,
            options=options,
            flash_message=exc.message,
        )
    return _web_redirect("/web/recurring", selected_id, flash="固定支出已确认。")


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
        return _web_redirect(
            "/web/recurring", selected_id, flash="页面已过期，请刷新后重新操作。"
        )
    try:
        pause_recurring_item(
            db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/recurring", selected_id, flash="页面已过期，请刷新后重新操作。"
            )
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
        return _web_redirect(
            "/web/recurring", selected_id, flash="页面已过期，请刷新后重新操作。"
        )
    try:
        resume_recurring_item(
            db, tenant_id=selected_id, public_id=public_id, expected_row_version=parsed
        )
    except AppError as exc:
        if exc.error == "state_conflict":
            return _web_redirect(
                "/web/recurring", selected_id, flash="页面已过期，请刷新后重新操作。"
            )
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
