"""/web 桌面账本 · 还款捕获复核 (ADR-0049 债务域 web 面 slice C3).

Android NotificationListenerService 自动捕获的还款通知 (花呗/借呗/白条/京东/美团月付/银行卡)
在这里进入**可操作复核**：pending 行把可行候选债逐项列为独立确认表单 (每项各带自己的
``target_debt_public_id`` + ``expected_row_version`` 隐藏字段——OCC 快照天然随目标走，浏览器
无 JS 也不会提交过期版本；服务端 match 给出建议项徽标与预选层级)，每行每渲染一套幂等键。
confirmed 行关联债名，dismissed 行沉降。视觉采用 #218 产品语言 (页头 eyebrow/摘要、feedback
条、审计表头+行、主次按钮层级、空态行动)，不继承 main 旧视觉。

**account-scoped 隐私 × 选定账本作用域**：还款捕获是**个人的**(你手机的支付通知)，
这里只列 viewer 自己创建的捕获 (``created_by_account_id == viewer``)，且收敛到**选定账本**
——每行都可操作，确认走选定账本的可写权限与该账本候选债的 OCC 快照；旧只读审计曾跨账本
聚合，可操作化后跨账本行提交必错 (服务侧按 tenant 锁草稿)，故列表与动作同域 (#218 验证过的
语义)。写动作仍要求**选定账本**可写 (``_require_selected_ledger_write``)。viewer 由
``_web_viewer_account_id`` 解析 (web session→会话账户;loopback owner-console=管理端→选定账本
owner 账户);viewer None (账本无活跃 owner) → 空态。

确认走共享命令服务 ``repayment_draft_command_service`` (与 /api 同一幂等握手：fingerprint
规范化、claim 与业务写同事务、HIT 返回 canonical 行);忽略走状态守卫终态翻转，可安全重放。
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
from app.routes._web_debt_write import _day_label
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _home_amount_label,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _sidebar_counts,
    parse_form_row_version_token,
    templates,
)
from app.routes.web_debts import _COUNTERPARTY_FALLBACK, _web_viewer_account_id
from app.schemas import RepaymentDraftConfirmRequest
from app.services.debt_service import (
    RepaymentDraftAuditRow,
    dismiss_repayment_draft,
    list_repayment_draft_audit_for_account,
)
from app.services.debt_service._repayment_draft import REPAYMENT_DRAFT_SOURCE_LABELS
from app.services.repayment_draft_command_service import confirm_repayment_draft_idempotently

router = APIRouter(prefix="/web/repayment-drafts", tags=["web"])

_AUDIT_INTRO = "手机自动捕获的还款通知在这里复核：确认记到哪笔欠款，或忽略。所有提交走服务端幂等事务，重复提交不会记成两笔。"
_EMPTY_TITLE = "还没有还款捕获"
_EMPTY_BODY = "手机 App 自动捕获的还款通知会在这里出现；确认记到哪笔欠款也在这一页完成。"

_STATUS_LABELS = {"pending": "待复核", "confirmed": "已记账", "dismissed": "已忽略"}
_STATUS_TONE = {"pending": "", "confirmed": "ok", "dismissed": "muted"}
_SUGGESTION_PREFIX = "系统猜测对应:{}"
_LINKED_PREFIX = "已记到:{}"
_DRAFT_ERROR_MESSAGES = {
    "debt_not_found": "这笔欠款不存在或不在当前账本。",
    "state_conflict": "这笔欠款刚被更新过，请刷新后重新确认。",
    "idempotency_key_required": "页面凭据缺失，请刷新后重新提交。",
    "idempotency_key_reused": "这次提交已经生效，不需要重复操作。",
    "idempotency_key_in_progress": "同一笔确认正在处理中，请稍候刷新查看。",
    "draft_not_found": "这条还款捕获不存在或已处理。",
    "draft_already_confirmed": "这条还款捕获已记过账。",
    "overpayment": "确认金额超过这笔欠款的剩余，请调整目标。",
}


def _actor_account_id(request: Request, db: Session, ledger_id: str) -> int:
    account_id = _web_viewer_account_id(request, db, ledger_id)
    if account_id is None:
        raise AppError("permission_denied", "当前账本没有可写入的账户。", status_code=403)
    return account_id


def _error_message(exc: AppError) -> str:
    return _DRAFT_ERROR_MESSAGES.get(exc.error, exc.message)


def _target_option(candidate, *, suggested_id: str | None, attempted_id: str | None) -> dict:
    return {
        "public_id": candidate.public_id,
        "row_version": candidate.row_version,
        "name": (candidate.counterparty_label or "").strip() or _COUNTERPARTY_FALLBACK["external"],
        # 候选的 remaining 是折叠后的本位币额 (match 服务只产 home-folded 行)，
        # RepaymentMatchCandidate 不带币种字段 → None 走 home 兜底。
        "remaining_label": _home_amount_label(candidate.remaining_amount_cents, None),
        "is_suggested": candidate.public_id == suggested_id,
        # 422 原地重渲染时回填「刚才选择」，不让用户在错误后猜自己点了哪项。
        "is_selected": attempted_id is not None and candidate.public_id == attempted_id,
    }


def _audit_row_view(row: RepaymentDraftAuditRow, *, attempted_target: str | None = None) -> dict:
    """一行审计记录的渲染视图；pending 行附带可操作上下文 (逐项候选 + 每行幂等键)。"""

    view: dict = {
        "public_id": row.public_id,
        "source_label": REPAYMENT_DRAFT_SOURCE_LABELS.get(row.source, row.source),
        "merchant": (row.merchant_label or "").strip() or None,
        "amount_label": _home_amount_label(row.amount_cents, row.home_currency_code),
        "captured_label": _day_label(row.captured_at),
        "status_label": _STATUS_LABELS.get(row.status, _STATUS_LABELS["pending"]),
        "status_tone": _STATUS_TONE.get(row.status, ""),
        "recede": row.status == "dismissed",
        "is_pending": row.status == "pending",
    }
    if row.status == "confirmed":
        name = row.linked_debt_label or _COUNTERPARTY_FALLBACK["external"]
        view["linked_line"] = _LINKED_PREFIX.format(name)
    elif row.status == "pending":
        view["idempotency_key"] = str(uuid4())
        view["targets"] = [
            _target_option(candidate, suggested_id=row.suggested_debt_public_id, attempted_id=attempted_target)
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
    attempted_target: str | None = None,
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
        options=options,
        selected_ledger_id=selected_id,
        page_title="还款捕获",
        sidebar_counts=_sidebar_counts(db, selected_id),
    )
    ctx["intro"] = _AUDIT_INTRO
    ctx["rows"] = [
        _audit_row_view(
            row,
            attempted_target=attempted_target if row.public_id == error_draft_public_id else None,
        )
        for row in rows
    ]
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


def _action_redirect(selected_id: str, *, flash_message: str | None = None, form_error: str | None = None) -> RedirectResponse:
    from app.routes.web_common import _web_redirect

    extra = {}
    if flash_message:
        extra["flash_message"] = flash_message
    if form_error:
        extra["form_error"] = form_error
    return _web_redirect("/web/repayment-drafts", selected_id, **extra)


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
    attempted_target = (target_debt_public_id or "").strip() or None
    try:
        expected = parse_form_row_version_token(expected_row_version)
        if not attempted_target:
            raise AppError("invalid_request", "请选择这笔还款对应的欠款。", status_code=422)
        if expected is None or expected < 0:
            raise AppError(
                "invalid_request",
                "欠款信息已经失效，请刷新后重新选择。",
                status_code=422,
            )
        payload = RepaymentDraftConfirmRequest(
            target_debt_public_id=attempted_target,
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
            status_code = exc.status_code
        else:
            message = "请选择这笔还款对应的欠款。"
            status_code = 422
        if status_code == 422:
            return _render_repayment_drafts(
                request,
                db,
                options=options,
                selected_id=selected_id,
                form_error=message,
                error_draft_public_id=public_id,
                attempted_target=attempted_target,
                status_code=422,
            )
        return _action_redirect(selected_id, form_error=message)
    return _action_redirect(selected_id, flash_message="已记入这笔还款。")


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
        return _action_redirect(selected_id, form_error=_error_message(exc))
    return _action_redirect(selected_id, flash_message="已忽略这条还款。")
