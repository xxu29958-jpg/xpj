"""Personal repayment captures: persistent original review and processed history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes._web_debt_write import _day_label
from app.routes._web_repayment_review import render_review, submit_review
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    templates,
)
from app.routes.web_debts import _COUNTERPARTY_FALLBACK, _web_viewer_account_id
from app.services.debt_service import (
    RepaymentDraftAuditRow,
    list_repayment_draft_audit_for_account,
)
from app.services.debt_service._repayment_draft import REPAYMENT_DRAFT_SOURCE_LABELS

router = APIRouter(prefix="/web/repayment-drafts", tags=["web"])

_AUDIT_INTRO = "手机自动捕获的还款通知在这里复核：确认记到哪笔欠款，或忽略。重复提交不会记成两笔。"
_EMPTY_TITLE = "还没有还款捕获"
_EMPTY_BODY = "手机 App 自动捕获的还款通知会在这里出现；打开原采集可核对金额、选择欠款或忽略。"

_STATUS_LABELS = {"pending": "待复核", "confirmed": "已记账", "dismissed": "已忽略"}
_STATUS_TONE = {"pending": "", "confirmed": "ok", "dismissed": "muted"}
_SUGGESTION_PREFIX = "系统猜测对应:{}"
_LINKED_PREFIX = "已记到:{}"
_DRAFT_ERROR_MESSAGES = {
    # 键必须与服务层真实抛出的错误码一致 (audit: 死键会让定制文案落空)。
    "debt_not_found": "这笔欠款不存在或不在当前账本。",
    "debt_overpay_rejected": "本次还款超过欠款剩余，请核对金额与目标。",
    "direct_fact_requires_external": "还款捕获只能记到外部欠款。",
    "direct_fact_requires_manual": "这笔往来需要走成员确认，不能直接记入还款。",
    "state_conflict": "这条还款捕获或欠款刚被更新过，请刷新后重新确认。",
    "idempotency_key_required": "页面凭据缺失，请刷新后重新提交。",
    "idempotency_key_reused": "这个提交编号已用于其他内容，请核对原提交；当前不能认定本次处理成功。",
    "idempotency_key_in_progress": "同一笔确认正在处理中，请稍候刷新查看。",
    "repayment_draft_not_found": "这条采集不在当前账号和账本中。",
}


def _actor_account_id(request: Request, db: Session, ledger_id: str) -> int:
    account_id = _web_viewer_account_id(request, db, ledger_id)
    if account_id is None:
        raise AppError("permission_denied", "当前账本没有可写入的账户。", status_code=403)
    return account_id


def _error_message(exc: AppError) -> str:
    return _DRAFT_ERROR_MESSAGES.get(exc.error, exc.message)


def _target_option(candidate, *, suggested_id: str | None) -> dict:
    return {
        "public_id": candidate.public_id,
        "row_version": candidate.row_version,
        "name": (candidate.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK["external"],
        # 候选的 remaining 是折叠后的本位币额 (match 服务只产 home-folded 行) ——
        # R13-8c 按候选 record 冻结币种渲染（不吃 env 兜底，与 confirm 的 R13-8b 同口径）。
        "remaining_label": _home_amount_label(candidate.remaining_amount_cents, candidate.home_currency_code),
        "is_suggested": candidate.public_id == suggested_id,
    }


def _audit_row_view(
    row: RepaymentDraftAuditRow,
) -> dict:
    """Read projection; original commands belong to the single capture review form."""

    view: dict = {
        "public_id": row.public_id,
        "source_label": REPAYMENT_DRAFT_SOURCE_LABELS.get(row.source, row.source),
        "merchant": (row.merchant_label or "").strip() or None,
        "amount_label": _home_amount_label(
            row.original_amount_minor if row.original_amount_minor is not None else row.amount_cents,
            row.original_currency_code or row.home_currency_code),
        "conversion_pending": row.status == "pending" and row.amount_cents is None,
        "home_currency_code": row.home_currency_code,
        "captured_label": _day_label(row.captured_at),
        "status_label": _STATUS_LABELS.get(row.status, _STATUS_LABELS["pending"]),
        "status_tone": _STATUS_TONE.get(row.status, ""),
        "recede": row.status == "dismissed",
        "is_pending": row.status == "pending",
        "committed_debt_public_id": row.committed_debt_public_id,
        "resolved_label": _day_label(row.resolved_at),
    }
    if row.status == "confirmed":
        name = row.linked_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["linked_line"] = _LINKED_PREFIX.format(name)
    elif row.status == "pending":
        view["targets"] = [
            _target_option(candidate, suggested_id=row.suggested_debt_public_id)
            for candidate in row.target_debts
        ]
        if row.has_suggestion:
            name = row.suggested_debt_label or _COUNTERPARTY_FALLBACK["external"]
            view["provenance"] = _SUGGESTION_PREFIX.format(name)
    return view


def _render_repayment_drafts(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    form_error: str | None = None,
    error_draft_public_id: str | None = None,
    flash_message: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    account_id = _web_viewer_account_id(request, db, selected_id)
    rows = (
        list_repayment_draft_audit_for_account(db, account_id=account_id, tenant_id=selected_id)
        if account_id is not None
        else []
    )
    ctx = _base_ctx(
        request,
        db=db,
        options=options,
        selected_ledger_id=selected_id,
        page_title="还款捕获",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _AUDIT_INTRO
    ctx["rows"] = [_audit_row_view(row) for row in rows]
    ctx["empty_title"] = _EMPTY_TITLE
    ctx["empty_body"] = _EMPTY_BODY
    ctx["form_error"] = form_error
    ctx["error_draft_public_id"] = error_draft_public_id
    ctx["flash_message"] = flash_message
    return templates.TemplateResponse(
        request=request,
        name="repayment_drafts.html",
        context=ctx,
        status_code=status_code,
    )



@router.get("", response_class=HTMLResponse)
def web_repayment_drafts(
    request: Request,
    ledger_id: str | None = None,
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
    flash_message: str | None = None,
    form_error: str | None = None,
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return _render_repayment_drafts(
        request,
        db,
        options=options,
        selected_id=selected_id,
        flash_message=flash_message,
        form_error=form_error,
    )


@router.get("/{public_id}", response_class=HTMLResponse)
def web_repayment_review(
    request: Request, public_id: str, ledger_id: str | None = None,
    _local: None = LocalOnly, db: Session = Depends(get_db),
) -> HTMLResponse:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    return render_review(request, db, options=options, selected_id=selected_id, public_id=public_id,
        account_id=_actor_account_id(request, db, selected_id))


@router.post("/{public_id}/review", response_class=HTMLResponse)
def web_submit_repayment_review(
    request: Request, public_id: str,
    ledger_id: str = Form(default=""), draft_public_id: str = Form(default=""),
    origin_binding: str = Form(default=""), review_action: str = Form(default=""),
    target_choice: str = Form(default=""), original_currency: str = Form(default=""),
    original_amount: str = Form(default=""), idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""), _local: None = LocalOnly, db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    values = {"draft_public_id": draft_public_id, "ledger_id": ledger_id, "origin_binding": origin_binding,
        "review_action": review_action, "target_choice": target_choice, "original_currency": original_currency,
        "original_amount": original_amount, "idempotency_key": idempotency_key}
    return submit_review(request, db, options=options, selected_id=selected_id, public_id=public_id,
        account_id=_actor_account_id(request, db, selected_id), values=values)
