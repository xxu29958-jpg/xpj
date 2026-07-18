"""HTML adapters for the two-party member repayment handshake."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes.web_common import (
    LocalOnly,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    parse_form_row_version_token,
)
from app.routes.web_debt_actions import (
    _STALE_MESSAGE,
    _action_redirect,
    _actor_account_id,
    _parse_major_minor,
)
from app.schemas import (
    MemberRepaymentProposalConfirmRequest,
    MemberRepaymentProposalCreateRequest,
    MemberRepaymentProposalRejectRequest,
    MemberRepaymentProposalWithdrawRequest,
)
from app.services.debt_proposal_command_service import (
    confirm_repayment_proposal_idempotently,
    create_repayment_proposal_idempotently,
    reject_repayment_proposal_idempotently,
    withdraw_repayment_proposal_idempotently,
)
from app.services.debt_service import get_participant_debt_response

router = APIRouter(prefix="/web/debts", tags=["web"])

_PROPOSAL_ERROR_MESSAGES = {
    "debt_already_voided": "这件事已经不用记啦。",
    "debt_not_found": "没有找到这份往来，或当前账户不是当事人。",
    "debt_overpay_rejected": "确认金额不能超过这份往来的剩余金额。",
    "repayment_proposal_already_pending": "这份还款已经发给对方，正在等确认。",
    "repayment_proposal_amount_invalid": "请填写大于 0、且不超过对方发来金额的数额。",
    "repayment_proposal_creditor_only": "只有收款方可以确认或回复这份还款。",
    "repayment_proposal_debtor_only": "只有付款方可以发起或撤回这份还款。",
    "repayment_proposal_expired": "这次确认已经过期，请让对方重新发一份。",
    "repayment_proposal_not_found": "这份待确认还款已经不存在，请刷新后再看。",
    "repayment_proposal_not_pending": "这份还款已经处理过，请刷新查看最新状态。",
    "repayment_proposal_requires_member_debt": "只有家庭成员之间的往来需要双方确认。",
}


def _proposal_error_message(exc: AppError) -> str:
    if exc.error == "state_conflict":
        return _STALE_MESSAGE
    return _PROPOSAL_ERROR_MESSAGES.get(exc.error, exc.message)


def _action_scope(
    request: Request,
    db: Session,
    ledger_id: str,
) -> tuple[str, int]:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    return selected_id, _actor_account_id(request, db, selected_id)


@router.post("/{public_id}/repayment-proposals")
def web_create_repayment_proposal(
    request: Request,
    public_id: str,
    ledger_id: str = Form(default=""),
    amount_major: str = Form(default=""),
    note: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    selected_id, actor_account_id = _action_scope(request, db, ledger_id)
    try:
        debt = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=selected_id,
            account_id=actor_account_id,
        )
        payload = MemberRepaymentProposalCreateRequest(
            proposed_amount_cents=_parse_major_minor(
                amount_major,
                currency_code=debt.home_currency_code,
                allow_negative=False,
            ),
            note=(note or "").strip() or None,
        )
        create_repayment_proposal_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = (
            _proposal_error_message(exc)
            if isinstance(exc, AppError)
            else "请填写正确的还款金额；想说的话最多 500 个字。"
        )
        return _action_redirect(
            public_id,
            selected_id,
            message=message,
            success=False,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="已经发给 TA 啦，等 TA 确认一下～",
        success=True,
    )


@router.post("/{public_id}/repayment-proposals/{proposal_public_id}/withdraw")
def web_withdraw_repayment_proposal(
    request: Request,
    public_id: str,
    proposal_public_id: str,
    ledger_id: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    selected_id, actor_account_id = _action_scope(request, db, ledger_id)
    try:
        withdraw_repayment_proposal_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            payload=MemberRepaymentProposalWithdrawRequest(),
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _proposal_error_message(exc) if isinstance(exc, AppError) else "暂时不能撤回，请刷新后再试。"
        return _action_redirect(
            public_id,
            selected_id,
            message=message,
            success=False,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="已经撤回啦。",
        success=True,
    )


@router.post("/{public_id}/repayment-proposals/{proposal_public_id}/confirm")
def web_confirm_repayment_proposal(
    request: Request,
    public_id: str,
    proposal_public_id: str,
    ledger_id: str = Form(default=""),
    amount_major: str = Form(default=""),
    expected_row_version: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    selected_id, actor_account_id = _action_scope(request, db, ledger_id)
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(
            public_id,
            selected_id,
            message=_STALE_MESSAGE,
            success=False,
        )
    try:
        debt = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=selected_id,
            account_id=actor_account_id,
        )
        confirmed_amount = (
            _parse_major_minor(
                amount_major,
                currency_code=debt.home_currency_code,
                allow_negative=False,
            )
            if (amount_major or "").strip()
            else None
        )
        confirm_repayment_proposal_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            payload=MemberRepaymentProposalConfirmRequest(
                confirmed_amount_cents=confirmed_amount,
                expected_row_version=expected,
            ),
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = (
            _proposal_error_message(exc) if isinstance(exc, AppError) else "请填写大于 0、且不超过对方发来金额的数额。"
        )
        return _action_redirect(
            public_id,
            selected_id,
            message=message,
            success=False,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="收到啦，谢谢 TA～",
        success=True,
    )


@router.post("/{public_id}/repayment-proposals/{proposal_public_id}/reject")
def web_reject_repayment_proposal(
    request: Request,
    public_id: str,
    proposal_public_id: str,
    ledger_id: str = Form(default=""),
    idempotency_key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    _local: None = LocalOnly,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    selected_id, actor_account_id = _action_scope(request, db, ledger_id)
    try:
        reject_repayment_proposal_idempotently(
            db,
            tenant_id=selected_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            payload=MemberRepaymentProposalRejectRequest(),
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except (AppError, ValidationError) as exc:
        message = _proposal_error_message(exc) if isinstance(exc, AppError) else "暂时不能回复，请刷新后再试。"
        return _action_redirect(
            public_id,
            selected_id,
            message=message,
            success=False,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="已经回复 TA「金额对不上」啦。",
        success=True,
    )
