"""HTML form adapters for external/manual Debt fact commands."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.routes import _web_debt_write
from app.routes._web_debt_money import parse_web_debt_major_minor
from app.routes._web_debt_repayment import (
    render_repayment_recovery,
    repayment_scope,
    require_repayment_binding,
)
from app.routes._web_debt_write import _parse_paid_at
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    parse_form_row_version_token,
)
from app.routes.web_debts import _render_debt_detail, _web_viewer_account_id
from app.schemas import (
    DebtAdjustmentCreateRequest,
    DebtForgiveCreateRequest,
    DebtKindSetRequest,
    DebtVoidCreateRequest,
    RepaymentCreateRequest,
    RepaymentVoidCreateRequest,
)
from app.services.debt_command_service import (
    forgive_debt_idempotently,
    record_adjustment_idempotently,
    record_repayment_idempotently,
    set_debt_kind_idempotently,
    void_debt_idempotently,
    void_repayment_idempotently,
)
from app.services.debt_service import get_debt_response

router = APIRouter(prefix="/web/debts", tags=["web"])

_STALE_MESSAGE = "另一端刚更新了这笔欠款。这次提交没有记录，下面已显示最新状态。"


def _action_redirect(
    public_id: str,
    ledger_id: str,
    *,
    message: str,
    success: bool,
) -> RedirectResponse:
    return _web_redirect(
        f"/web/debts/{public_id}",
        ledger_id,
        msg=message,
        flash_type="success" if success else "error",
    )


def _error_message(exc: AppError) -> str:
    if exc.error == "state_conflict":
        return _STALE_MESSAGE
    return exc.message


def _render_action_error(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    public_id: str,
    kind: str,
    message: str,
    draft: dict[str, str] | None = None,
    target_public_id: str = "",
    status_code: int,
) -> HTMLResponse:
    db.rollback()
    return _render_debt_detail(
        request,
        db,
        options=options,
        selected_id=selected_id,
        public_id=public_id,
        action_kind=kind,
        action_error=message,
        action_draft=draft,
        action_target_public_id=target_public_id,
        action_conflict=message == _STALE_MESSAGE,
        status_code=status_code,
    )


def _actor_account_id(request: Request, db: Session, ledger_id: str) -> int:
    account_id = _web_viewer_account_id(request, db, ledger_id)
    if account_id is None:
        raise AppError(
            "permission_denied",
            "当前账本没有可用于记录事实的账户。",
            status_code=403,
        )
    return account_id


def _repayment_outcome(
    request, db, *, options, selected_id, public_id, values=None,
    error="", result="", status_code=200, ack=None,
    rejected=False,
):
    try:
        return _render_debt_detail(
            request, db, options=options, selected_id=selected_id, public_id=public_id,
            action_kind="repayment" if values is not None else None,
            action_error=error, action_draft=values, status_code=status_code,
            repayment_ack=ack, repayment_result=result,
            repayment_rejected=rejected,
        )
    except (AppError, SQLAlchemyError):
        db.rollback()
        return render_repayment_recovery(
            request, db, options=options, selected_id=selected_id, public_id=public_id,
            values=values, error=error, result=result, status_code=status_code, ack=ack,
        )


@router.get("/{public_id}/repayments", include_in_schema=False)
def web_repayment_return(public_id: str, ledger_id: str = "", _local: None = LocalOnly):
    return _web_redirect(f"/web/debts/{public_id}", ledger_id)


@router.post("/{public_id}/repayments")
def web_record_repayment(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    debt_public_id: str = Form(default=""),
    origin_binding: str = Form(default=""),
    home_currency_code: str = Form(default=""),
    amount_major: str = Form(default=""),
    paid_at: str = Form(default=""),
    paid_at_timezone: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(db, ledger_id, options, request=request)
    values = {
        "ledger_id": ledger_id, "debt_public_id": debt_public_id,
        "origin_binding": origin_binding, "home_currency_code": home_currency_code,
        "amount_major": amount_major, "paid_at": paid_at,
        "paid_at_timezone": paid_at_timezone or _web_debt_write.accounting_zone().key,
        "expected_row_version": expected_row_version, "idempotency_key": idempotency_key,
    }
    attempted = False
    try:
        require_repayment_binding(request, db, values=values, public_id=public_id)
        _require_selected_ledger_write(options, selected_id)
        expected = parse_form_row_version_token(expected_row_version)
        if expected is None:
            raise AppError("state_conflict", "原提交缺少有效版本，输入仍保留。请核对欠款后重新填写。", status_code=409)
        debt = get_debt_response(db, tenant_id=selected_id, public_id=public_id)
        if home_currency_code and home_currency_code != debt.home_currency_code:
            raise AppError("debt_currency_changed", "原还款币种与这笔欠款不一致，请核对原提交。", status_code=409)
        # Bare native clients predate retained forms. Once received, freeze their
        # existing record denomination and date interpretation in the return form.
        values["home_currency_code"] = debt.home_currency_code
        values["debt_public_id"] = public_id
        payload = RepaymentCreateRequest(
            amount_cents=parse_web_debt_major_minor(amount_major, currency_code=debt.home_currency_code, allow_negative=False),
            paid_at=_parse_paid_at(paid_at, values["paid_at_timezone"]), expected_row_version=expected,
        )
        attempted = True
        receipt = record_repayment_idempotently(
            db, tenant_id=selected_id, actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id, payload=payload, idempotency_key=idempotency_key.strip() or None,
        )
    except (AppError, ValidationError, SQLAlchemyError) as exc:
        db.rollback()
        status = exc.status_code if isinstance(exc, AppError) else 503 if isinstance(exc, SQLAlchemyError) else 422
        unknown = status >= 500 or isinstance(exc, AppError) and exc.error == "idempotency_key_in_progress"
        invalid_amount = isinstance(exc, AppError) and exc.error in {"debt_overpay_rejected", "debt_amount_invalid"}
        result = "submitted" if unknown else "rejected" if invalid_amount or not attempted and status == 422 else "blocked"
        message = _error_message(exc) if isinstance(exc, AppError) else "还款结果暂未确认，请继续核实原提交。" if unknown else "还款信息不完整，请检查后重试。"
        return _repayment_outcome(
            request, db, options=options, selected_id=selected_id, public_id=public_id,
            values=values, error=message, result=result, status_code=status,
            rejected=isinstance(exc, AppError) and exc.error == "state_conflict",
        )
    # Exact command receipt precedes the independent detail query. Even when that
    # query fails, the original acceptance can be shown and acknowledged locally.
    ack = {"scope": repayment_scope(request, db), "clientRef": idempotency_key,
           "repaymentPublicId": receipt.repayment_public_id, "values": {k: v for k, v in values.items() if k != "idempotency_key"}}
    return _repayment_outcome(request, db, options=options, selected_id=selected_id, public_id=public_id, ack=ack)


@router.post("/{public_id}/adjustments")
def web_record_adjustment(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    amount_major: str = Form(default=""),
    reason: str = Form(default=""),
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
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        debt = get_debt_response(
            db,
            tenant_id=selected_id,
            public_id=public_id,
        )
        payload = DebtAdjustmentCreateRequest(
            amount_cents=parse_web_debt_major_minor(
                amount_major,
                currency_code=debt.home_currency_code,
                allow_negative=True,
            ),
            reason=(reason or "").strip(),
            expected_row_version=expected,
        )
        record_adjustment_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _error_message(exc) if isinstance(exc, AppError) else "请填写调整金额和原因。"
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="adjustment",
            message=message,
            draft={"amount_major": amount_major, "reason": reason},
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="本金调整事实已记录。",
        success=True,
    )


@router.post("/{public_id}/repayment-voids")
def web_void_repayment(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    repayment_public_id: str = Form(default=""),
    reason: str = Form(default=""),
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
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        payload = RepaymentVoidCreateRequest(
            repayment_public_id=(repayment_public_id or "").strip(),
            reason=(reason or "").strip(),
            expected_row_version=expected,
        )
        void_repayment_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _error_message(exc) if isinstance(exc, AppError) else "请填写撤销原因。"
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="repayment_void",
            message=message,
            draft={"reason": reason},
            target_public_id=repayment_public_id,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="误记还款已撤销，原始记录仍保留。",
        success=True,
    )


@router.post("/{public_id}/void")
def web_void_debt(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    reason: str = Form(default=""),
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
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        payload = DebtVoidCreateRequest(
            reason=(reason or "").strip(),
            expected_row_version=expected,
        )
        void_debt_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _error_message(exc) if isinstance(exc, AppError) else "请填写作废原因。"
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="void",
            message=message,
            draft={"reason": reason},
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="欠款已作废，原始事实仍保留。",
        success=True,
    )


@router.post("/{public_id}/kind")
def web_set_debt_kind(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    debt_kind: str = Form(default=""),
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
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        payload = DebtKindSetRequest(
            debt_kind=(debt_kind or "").strip(),
            expected_row_version=expected,
        )
        set_debt_kind_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _error_message(exc) if isinstance(exc, AppError) else "请选择正确的还款类型。"
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="kind",
            message=message,
            draft={"debt_kind": debt_kind},
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="还款类型已更新。",
        success=True,
    )


@router.post("/{public_id}/forgive")
def web_forgive_member_debt(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
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
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        forgive_debt_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=_actor_account_id(request, db, selected_id),
            public_id=public_id,
            payload=DebtForgiveCreateRequest(expected_row_version=expected),
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _error_message(exc) if isinstance(exc, AppError) else "暂时不能免除这份往来。"
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="forgive",
            message=message,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="这份往来已免除，对方无需再还。",
        success=True,
    )
