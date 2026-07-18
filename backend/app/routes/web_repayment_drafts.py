"""Browser review inbox for captured repayments.

The page mirrors the Android contract: a notification capture remains a draft
until the capturing account explicitly chooses an open external/manual Debt and
confirms it, or dismisses it.  Resolved drafts remain visible as receded audit
history.

Privacy and authority are both two-dimensional:

* every read/write is scoped to the selected ledger; and
* the service additionally scopes each draft to the capturing account.

The selected-ledger writer gate is still mandatory for browser writes.  The
confirm command reuses the JSON API's idempotency + OCC transaction, while
dismiss is a status-guarded idempotent terminal flip.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    _web_redirect,
    parse_form_row_version_token,
    templates,
)
from app.routes.web_debt_proposal_views import _day_label
from app.routes.web_debts import _COUNTERPARTY_FALLBACK, _web_viewer_account_id
from app.schemas import RepaymentDraftConfirmRequest
from app.services.debt_service import (
    RepaymentDraftAuditRow,
    dismiss_repayment_draft,
    list_repayment_draft_audit_for_account,
)
from app.services.debt_service._repayment_draft import REPAYMENT_DRAFT_SOURCE_LABELS
from app.services.repayment_draft_command_service import (
    confirm_repayment_draft_idempotently,
)

router = APIRouter(prefix="/web/repayment-drafts", tags=["web"])

_INTRO = "从支付通知里捕获到的还款，先核对再对应到一笔欠款，绝不自动记账。"
_EMPTY_TITLE = "没有待确认的还款"
_EMPTY_BODY = "开启通知捕获后，花呗 / 白条 / 美团月付 / 信用卡的还款通知会进入这里等待核对。"

_STATUS_LABELS = {"pending": "待确认", "confirmed": "已记账", "dismissed": "已忽略"}
_STATUS_TONE = {"pending": "", "confirmed": "ok", "dismissed": "muted"}
_SUGGESTION_PREFIX = "建议还到「{}」"
_LINKED_PREFIX = "已记到「{}」"

_ERROR_MESSAGES = {
    "debt_not_found": "这笔欠款已经不可用，请刷新后重新选择。",
    "debt_overpay_rejected": "这笔还款超过了欠款的剩余金额，请刷新后重新选择。",
    "direct_fact_requires_external": "还款草稿只能对应外部欠款。",
    "direct_fact_requires_manual": "这笔往来需要走成员确认，不能直接记入还款。",
    "idempotency_key_in_progress": "这笔还款正在处理，请稍后刷新查看。",
    "idempotency_key_required": "页面操作凭证已失效，请刷新后重试。",
    "idempotency_key_reused": "页面操作凭证已过期，请重试这次选择。",
    "repayment_draft_not_found": "没有找到这条待确认还款，或它不属于当前账户。",
    "state_conflict": "这条还款或欠款已在其它端改变，请刷新后重新选择。",
}


def _parse_target(
    target_debt_public_id: str,
    expected_row_version: str,
) -> tuple[str, int]:
    public_id = (target_debt_public_id or "").strip()
    if not public_id:
        raise AppError("invalid_request", "请选择这笔还款对应的欠款。", status_code=422)
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None or expected < 0:
        raise AppError(
            "invalid_request",
            "欠款信息已经失效，请刷新后重新选择。",
            status_code=422,
        )
    return public_id, expected


def _audit_row_view(
    row: RepaymentDraftAuditRow,
    *,
    selected_target_public_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Reduce a service row to display-only labels and form-safe target fields."""

    targets = [
        {
            "public_id": target.public_id,
            "row_version": target.row_version,
            "name": (target.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK["external"],
            "remaining_label": _home_amount_label(
                target.remaining_amount_cents,
                row.home_currency_code,
            ),
            "is_suggested": target.public_id == row.suggested_debt_public_id,
            "is_selected": target.public_id == selected_target_public_id,
        }
        for target in row.target_debts
    ]
    view: dict = {
        "public_id": row.public_id,
        "source_label": REPAYMENT_DRAFT_SOURCE_LABELS.get(row.source, row.source),
        "merchant": (row.merchant_label or "").strip() or None,
        "amount_label": _home_amount_label(row.amount_cents, row.home_currency_code),
        "captured_label": _day_label(row.captured_at),
        "status": row.status,
        "status_label": _STATUS_LABELS.get(row.status, _STATUS_LABELS["pending"]),
        "status_tone": _STATUS_TONE.get(row.status, ""),
        "recede": row.status == "dismissed",
        "is_pending": row.status == "pending",
        "targets": targets,
        "idempotency_key": idempotency_key or str(uuid4()),
    }
    if row.status == "confirmed":
        name = row.linked_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["linked_line"] = _LINKED_PREFIX.format(name)
    elif row.status == "pending" and row.has_suggestion:
        name = row.suggested_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["provenance"] = _SUGGESTION_PREFIX.format(name)
    return view


def _selected_can_write(options, selected_id: str) -> bool:
    selected = next((option for option in options if option.ledger_id == selected_id), None)
    return selected is not None and selected.role in {"owner", "member"}


def _actor_account_id(request: Request, db: Session, selected_id: str) -> int:
    account_id = _web_viewer_account_id(request, db, selected_id)
    if account_id is None:
        raise AppError(
            "permission_denied",
            "当前账本没有可用于处理还款的账户。",
            status_code=403,
        )
    return account_id


def _render_repayment_drafts(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    message: str | None = None,
    error: str | None = None,
    error_draft_public_id: str | None = None,
    form_values: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    account_id = _web_viewer_account_id(request, db, selected_id)
    service_rows = (
        list_repayment_draft_audit_for_account(
            db,
            account_id=account_id,
            tenant_id=selected_id,
        )
        if account_id is not None
        else []
    )
    values = form_values or {}
    rows = [
        _audit_row_view(
            row,
            selected_target_public_id=(
                values.get("target_debt_public_id") if row.public_id == error_draft_public_id else None
            ),
            idempotency_key=(values.get("idempotency_key") if row.public_id == error_draft_public_id else None),
        )
        for row in service_rows
    ]
    ctx = _base_ctx(
        request,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还款待确认",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx.update(
        {
            "intro": _INTRO,
            "rows": rows,
            "empty_title": _EMPTY_TITLE,
            "empty_body": _EMPTY_BODY,
            "can_write": _selected_can_write(options, selected_id),
            "flash_message": message or "",
            "form_error": error or "",
            "error_draft_public_id": error_draft_public_id or "",
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="repayment_drafts.html",
        context=ctx,
        status_code=status_code,
    )


def _action_redirect(
    selected_id: str,
    *,
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    return _web_redirect(
        "/web/repayment-drafts",
        selected_id,
        msg=message or "",
        error=error or "",
    )


def _error_message(exc: AppError) -> str:
    return _ERROR_MESSAGES.get(exc.error, exc.message)


@router.get("", response_class=HTMLResponse)
def web_repayment_drafts(
    request: Request,
    ledger_id: str | None = None,
    msg: str | None = None,
    error: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_repayment_drafts(
        request,
        db,
        options=options,
        selected_id=selected_id,
        message=msg,
        error=error,
    )


@router.post("/{public_id}/confirm", response_class=HTMLResponse)
def web_confirm_repayment_draft(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    target_debt_public_id: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    form_values = {
        "target_debt_public_id": target_debt_public_id,
        "expected_row_version": expected_row_version,
        "idempotency_key": idempotency_key,
    }
    try:
        target_debt_public_id, expected = _parse_target(
            target_debt_public_id,
            expected_row_version,
        )
        payload = RepaymentDraftConfirmRequest(
            target_debt_public_id=target_debt_public_id,
            expected_row_version=expected,
        )
        confirm_repayment_draft_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        db.rollback()
        if isinstance(exc, AppError):
            message = _error_message(exc)
            error_code = exc.error
            status_code = exc.status_code
        else:
            message = "请选择这笔还款对应的欠款。"
            error_code = "invalid_request"
            status_code = 422
        if status_code == 422:
            if error_code in {"idempotency_key_required", "idempotency_key_reused"}:
                form_values["idempotency_key"] = str(uuid4())
            return _render_repayment_drafts(
                request,
                db,
                options=options,
                selected_id=selected_id,
                error=message,
                error_draft_public_id=public_id,
                form_values=form_values,
                status_code=422,
            )
        return _action_redirect(selected_id, error=message)
    return _action_redirect(selected_id, message="已记入这笔还款。")


@router.post("/{public_id}/dismiss")
def web_dismiss_repayment_draft(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    try:
        dismiss_repayment_draft(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            commit=True,
        )
    except AppError as exc:
        db.rollback()
        return _action_redirect(selected_id, error=_error_message(exc))
    return _action_redirect(selected_id, message="已忽略这条还款。")
