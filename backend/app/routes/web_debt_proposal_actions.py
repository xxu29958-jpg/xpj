"""HTML adapters for the two-party member repayment handshake."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.errors import AppError
from app.money_carrier import MAX_MAJOR_DECIMAL_TEXT_LENGTH
from app.routes._web_debt_money import parse_web_debt_major_minor
from app.routes._web_debt_write import (
    PROPOSAL_CONFIRM_AMOUNT_FIELD,
    PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY,
)
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
    _render_action_error,
)
from app.routes.web_debts import _render_debt_detail
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
        return "这份还款刚被对方更新过，你刚才的确认没有生效。"
    return _PROPOSAL_ERROR_MESSAGES.get(exc.error, exc.message)


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
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    actor_account_id = _actor_account_id(request, db, selected_id)
    try:
        debt = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=selected_id,
            account_id=actor_account_id,
        )
        payload = MemberRepaymentProposalCreateRequest(
            proposed_amount_cents=parse_web_debt_major_minor(
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
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="proposal_create",
            message=message,
            draft={"amount_major": amount_major, "note": note},
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
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
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    actor_account_id = _actor_account_id(request, db, selected_id)
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
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="proposal_withdraw",
            message=message,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="已经撤回啦。",
        success=True,
    )


def _parse_confirmed_amount(raw: str, *, currency_code: str) -> int | None:
    """D3 确认金额解析：空串 = 按对方申报全额确认 (``None``，服务层语义)，这是一个
    **显式分支**而非 Form 默认值巧合；非空走共享的 minor-unit 解析 (两位小数 / JPY/KRW
    零小数 / 必须大于 0)，非法输入抛 422，由路由原地重渲染并锚定到金额输入。"""
    text = raw or ""
    if not text:
        return None
    return parse_web_debt_major_minor(
        text,
        currency_code=currency_code,
        allow_negative=False,
    )


def _canonical_alias_comparison_text(raw: str) -> str:
    """Normalize only the released two-alias comparison's leading zero form.

    D3's N-1 contract compared the new and legacy fields by numeric minor-unit
    value, so ``050`` and ``50`` were equivalent.  Keep that compatibility at
    the adapter boundary without weakening the canonical parser for a normal
    single-field submission, whitespace, or exponent notation.
    """

    # Keep work bounded by the canonical wire limit before scanning an
    # attacker-controlled form value. Returning the original text makes the
    # shared parser reject an overlong carrier with its existing 422 contract.
    if not raw or len(raw) > MAX_MAJOR_DECIMAL_TEXT_LENGTH:
        return raw

    sign_end = 1 if raw[0] == "-" else 0
    index = sign_end
    while index < len(raw) and "0" <= raw[index] <= "9":
        index += 1
    whole_end = index
    if whole_end == sign_end:
        return raw

    if index < len(raw):
        if raw[index] != "." or index + 1 == len(raw):
            return raw
        index += 1
        while index < len(raw) and "0" <= raw[index] <= "9":
            index += 1
        if index != len(raw):
            return raw

    first_significant = sign_end
    while first_significant < whole_end and raw[first_significant] == "0":
        first_significant += 1
    whole = raw[first_significant:whole_end] or "0"
    return f"{raw[:sign_end]}{whole}{raw[whole_end:]}"


def _confirm_amount_raw(confirmed_amount_major: str, legacy_amount_major: str, *, currency_code: str) -> str:
    """N-1 字段优先级：任一别名单独提交均接受；两者皆空返回空串 (显式全额分支在
    ``_parse_confirmed_amount``)。两者均非空时**按债务币种解析后**比较 minor-unit 值
    (等值格式如 50.0/50.00 视为同一提交；已发布的双字段 JPY ``050``/``50``
    仅在比较边界归一化，单字段、空白和指数形式仍按共享 canonical parser 拒绝)；任一非法 →
    维持非法金额 422 族；
    解析后真不同 = 客户端序列化/迁移错误 → 抛冲突 422 (不写成错误的还款金额事实)。"""
    new_text = confirmed_amount_major or ""
    legacy_text = legacy_amount_major or ""
    if new_text and legacy_text:
        new_comparison_text = _canonical_alias_comparison_text(new_text)
        legacy_comparison_text = _canonical_alias_comparison_text(legacy_text)
        new_minor = parse_web_debt_major_minor(
            new_comparison_text,
            currency_code=currency_code,
            allow_negative=False,
        )
        legacy_minor = parse_web_debt_major_minor(
            legacy_comparison_text,
            currency_code=currency_code,
            allow_negative=False,
        )
        if new_minor != legacy_minor:
            raise AppError(
                "invalid_request",
                "这次提交里有两个不一样的金额，请刷新后只保留一个再确认。",
                status_code=422,
            )
        return new_comparison_text
    return new_text or legacy_text


def _confirm_amount_error_rerender(
    request: Request,
    db: Session,
    *,
    options,
    selected_id: str,
    public_id: str,
    proposal_public_id: str,
    exc: AppError,
    attempted: str,
) -> HTMLResponse:
    """确认金额失败原地重渲染：输入错误为 422，OCC conflict 为 409。
    错误锚定到本次确认语境，什么都不写 (不落 redirect-flash 让用户误以为操作已生效)。
    ``proposal_public_id`` 把错误钉在**本次提交**的 proposal 语境上：提交后在途 proposal
    被处理/换了一条时，错误仍渲染在被提交的 proposal 区域，不隐藏也不挂到新的在途条目。"""
    db.rollback()
    return _render_debt_detail(
        request,
        db,
        options=options,
        selected_id=selected_id,
        public_id=public_id,
        confirm_amount_error=_proposal_error_message(exc),
        confirm_amount_value=attempted,
        confirm_error_proposal_id=proposal_public_id,
        status_code=exc.status_code,
    )


def _confirm_business_error_redirect(
    public_id: str,
    selected_id: str,
    exc: AppError | ValidationError,
) -> RedirectResponse:
    message = (
        _proposal_error_message(exc) if isinstance(exc, AppError) else "请填写大于 0、且不超过对方发来金额的数额。"
    )
    return _action_redirect(
        public_id,
        selected_id,
        message=message,
        success=False,
    )


def _confirm_proposal_command(
    db: Session,
    *,
    selected_id: str,
    actor_account_id: int,
    public_id: str,
    proposal_public_id: str,
    confirmed_amount: int | None,
    expected: int,
    idempotency_key: str,
) -> None:
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


# D3 uses the shared current field name; the legacy alias remains an explicit N-1 form boundary.
@router.post("/{public_id}/repayment-proposals/{proposal_public_id}/confirm")
def web_confirm_repayment_proposal(
    request: Request,
    public_id: str,
    proposal_public_id: str,
    ledger_id: str = Form(default=""),
    confirmed_amount_major: str = Form(default="", alias=PROPOSAL_CONFIRM_AMOUNT_FIELD),
    amount_major: str = Form(default="", alias=PROPOSAL_CONFIRM_AMOUNT_FIELD_LEGACY, deprecated=True),
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
    actor_account_id = _actor_account_id(request, db, selected_id)
    expected = parse_form_row_version_token(expected_row_version)
    if expected is None:
        return _action_redirect(public_id, selected_id, message=_STALE_MESSAGE, success=False)
    try:
        debt = get_participant_debt_response(
            db,
            public_id=public_id,
            ledger_id=selected_id,
            account_id=actor_account_id,
        )
    except AppError as exc:
        return _confirm_business_error_redirect(public_id, selected_id, exc)
    try:
        attempted_amount = _confirm_amount_raw(
            confirmed_amount_major,
            amount_major,
            currency_code=debt.home_currency_code,
        )
        confirmed_amount = _parse_confirmed_amount(
            attempted_amount,
            currency_code=debt.home_currency_code,
        )
    except AppError as exc:
        return _confirm_amount_error_rerender(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            exc=exc,
            attempted=(confirmed_amount_major or "").strip() or (amount_major or "").strip(),
        )
    try:
        _confirm_proposal_command(
            db,
            selected_id=selected_id,
            actor_account_id=actor_account_id,
            public_id=public_id,
            proposal_public_id=proposal_public_id,
            confirmed_amount=confirmed_amount,
            expected=expected,
            idempotency_key=idempotency_key,
        )
    except (AppError, ValidationError) as exc:
        if isinstance(exc, AppError) and exc.error == "state_conflict":
            return _confirm_amount_error_rerender(
                request,
                db,
                options=options,
                selected_id=selected_id,
                public_id=public_id,
                proposal_public_id=proposal_public_id,
                exc=exc,
                attempted=attempted_amount,
            )
        return _confirm_business_error_redirect(public_id, selected_id, exc)
    return _action_redirect(public_id, selected_id, message="收到啦，谢谢 TA～", success=True)


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
) -> Response:
    options = _list_ledger_options(db)
    selected_id = _resolve_selected_ledger_id(
        db,
        ledger_id,
        options,
        request=request,
    )
    _require_selected_ledger_write(options, selected_id)
    actor_account_id = _actor_account_id(request, db, selected_id)
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
        return _render_action_error(
            request,
            db,
            options=options,
            selected_id=selected_id,
            public_id=public_id,
            kind="proposal_reject",
            message=message,
            status_code=exc.status_code if isinstance(exc, AppError) else 422,
        )
    return _action_redirect(
        public_id,
        selected_id,
        message="已经回复 TA「金额对不上」啦。",
        success=True,
    )
