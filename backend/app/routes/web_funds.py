"""Native funds forms use the same commands and retained browser intents as the API."""
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.routes._web_draft_binding import (
    browser_draft_scope,
    draft_ack_response,
    draft_error_response,
    draft_refusal_result,
    require_draft_binding,
)
from app.routes._web_funds_capture import capture_context, funds_result_href
from app.routes._web_funds_values import (
    account_create_payload,
    account_edit_payload,
    form_defaults,
    payment_payload,
    posting_payload,
)
from app.routes._web_installments import installment_payload, selected_installment_values
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas.funds import CreditPaymentVoid, FinancialAccountView
from app.services.credit_history_adoption import existing_debt_choices
from app.services.currency_common import minor_amount_label, supported_currency_codes
from app.services.funds_account_choices import ACCOUNT_CHOICES
from app.services.funds_commands import (
    claim_funds,
    create_account,
    edit_account,
    funds_request_is_unpublished,
    replay_funds,
)
from app.services.funds_credit_payment import pay_credit
from app.services.funds_payment_correction import void_credit_payment
from app.services.funds_posting_service import post_account_activity
from app.services.funds_query import account_view, funds_overview, get_account, list_accounts
from app.services.installment_commands import save_installments
from app.services.installment_query import installments_view
from app.services.ledger_calendar_service import current_ledger_date
from app.tenants import AuthContext

router = APIRouter(prefix="/web/funds", tags=["web"])


def _scope(request, db, ledger_id):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None or auth.ledger_id != selected:
        raise AppError("invalid_token", "请先登录此浏览器，资金账户按你的身份显示。", status_code=401)
    return options, selected, auth


def _render(request: Request, db: Session, *, ledger_id: str, task: str = "", account_id: str = "", values: dict | None = None,
            error: str | None = None, result: str = "", status: int = 200, agreement_id: str = "", repayment_id: str = "", prepared_from: str = "") -> HTMLResponse:
    options, selected, auth = _scope(request, db, ledger_id)
    accounts = list_accounts(db, ledger_id=selected, actor_account_id=auth.account_id)
    account = account_view(db, get_account(db, ledger_id=selected, actor_account_id=auth.account_id,
        public_id=account_id), actor_account_id=auth.account_id, with_movements=True) if account_id else None
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="资金账户")
    defaults = form_defaults(account, task, ctx["home_currency_code"],
        current_ledger_date(db, ledger_id=account.ledger_id if account else selected), repayment_id)
    installments = installments_view(db, get_account(db, ledger_id=selected, actor_account_id=auth.account_id,
        public_id=account_id)) if account and account.kind == "credit" else None
    defaults.update(selected_installment_values(installments, agreement_id, defaults["currency_code"]))
    source_id = values.get("source_repayment_draft_id", "") if values is not None else request.query_params.get("source_repayment_draft_id", "")
    capture, captured_values = capture_context(db, auth, source_id, account)
    if capture and task in {"repay", "create"}:
        defaults.update(captured_values)
    ctx.update(accounts=accounts, account=account, task=task, values=defaults if values is None else values,
        source_capture=capture,
        funds_scope=browser_draft_scope(db, request), funds_result=result, funds_prepared_from=prepared_from, error=error,
        currency_options=sorted(supported_currency_codes()), money=minor_amount_label,
        funds_can_write=auth.role in {"owner", "member"}, installments=installments, account_choices=ACCOUNT_CHOICES,
        existing_debts=existing_debt_choices(db, ledger_id=selected, actor_account_id=auth.account_id) if task == "create" else [])
    ctx["funds_overview"] = funds_overview(db, ledger_id=selected, actor_account_id=auth.account_id)
    return templates.TemplateResponse(request=request, name="funds.html", context=ctx, status_code=status,
        headers={"Cache-Control": "no-store"})


@router.get("")
def web_funds(request: Request, ledger_id: str = "", task: str = "", account_id: str = "",
        agreement_id: str = "", repayment_id: str = "", _local: None = LocalOnly, db: Session = Depends(get_db)):
    if task not in {"", "create", "edit", "repay", "income", "loan", "transfer", "reconciliation", "installments", "void_repayment"} or (task not in {"", "create"} and not account_id):
        raise AppError("invalid_request", "请从资金账户选择要办理的事项。", status_code=422)
    return _render(request, db, ledger_id=ledger_id, task=task, account_id=account_id, agreement_id=agreement_id, repayment_id=repayment_id)


def _run(db, auth, values, payload, handler, operation, review) -> FinancialAccountView | None:
    target = values.get("account_id") or None
    if review:
        claimed = claim_funds(db, auth, payload, values["idempotency_key"], operation, target)
        if claimed is None:
            return replay_funds(db, auth, values["idempotency_key"])
        db.rollback()
        return None
    kwargs = {"public_id": target} if target else {}
    return handler(db, auth=auth, payload=payload, key=values["idempotency_key"], **kwargs)


def _execute(db: Session, auth: AuthContext, values: dict[str, str], *, review: bool = False) -> FinancialAccountView | None:
    mode = values["mode"]
    if mode == "void_repayment":
        payload = CreditPaymentVoid(expected_row_version=values["expected_row_version"],
            repayment_public_id=values["repayment_public_id"], occurred_on=values["occurred_on"], reason=values["note"])
        return _run(db, auth, values, payload, void_credit_payment, "void_credit_payment", review)
    if mode == "installments":
        account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=values["account_id"])
        if account.currency_code != values["currency_code"]:
            raise AppError("state_conflict", "原合约币种已变化，请保留原输入核对。", status_code=409)
        return _run(db, auth, values, installment_payload(values), save_installments, "save_installment_agreement", review)
    if mode == "create":
        return _run(db, auth, values, account_create_payload(values), create_account, "create_financial_account", review)
    if mode == "edit":
        return _run(db, auth, values, account_edit_payload(values), edit_account, "edit_financial_account", review)
    if mode in {"income", "loan", "transfer", "reconciliation"}:
        return _run(db, auth, values, posting_payload(db, auth, values), post_account_activity, "post_account_activity", review)
    if mode == "repay":
        return _run(db, auth, values, payment_payload(db, auth, values), pay_credit, "pay_credit_from_account", review)
    raise AppError("invalid_request", "请选择要办理的资金事项。", status_code=422)


@router.post("/save")
async def web_save_funds(request: Request, expected_row_version: str = Form(""),
        _local: None = LocalOnly, db: Session = Depends(get_db)):
    values = dict(await request.form())
    values["expected_row_version"] = expected_row_version
    ledger = str(values.get("ledger_id", ""))
    try:
        auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
        _require_selected_ledger_write(_list_ledger_options(db), ledger)
        if values.get("review_latest"):
            original = _execute(db, auth, values, review=True)
            if original is not None:
                href = funds_result_href(values, ledger, original.public_id)
                return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=values["idempotency_key"],
                    receipt=original, next_href=href) or _web_redirect("/web/funds", ledger, account_id=original.public_id)
            if values.get("account_id"):
                current = account_view(db, get_account(db, ledger_id=ledger, actor_account_id=auth.account_id,
                    public_id=values["account_id"]), actor_account_id=auth.account_id)
                if current.currency_code != values["currency_code"]:
                    raise AppError("state_conflict", "原输入币种与账户不一致，请核对原输入。", status_code=409)
                values.update(expected_row_version=str(current.row_version), calendar_revision=str(current.calendar_revision))
            if values.get("payer_public_id"):
                payer = get_account(db, ledger_id=ledger, actor_account_id=auth.account_id, public_id=values["payer_public_id"])
                if payer.currency_code != values["payer_currency_code"]:
                    raise AppError("state_conflict", "原付款币种与账户不一致，请核对原输入。", status_code=409)
                values["payer_row_version"] = str(payer.row_version)
            return _render(request, db, ledger_id=ledger, task=values["mode"], account_id=values.get("account_id", ""),
                values={**values, "idempotency_key": str(uuid4())}, result="prepared", prepared_from=values["idempotency_key"])
        receipt = _execute(db, auth, values)
    except (AppError, ValidationError, KeyError, ValueError) as exc:
        db.rollback()
        error = exc if isinstance(exc, AppError) else AppError("invalid_request", "请检查账户、金额和日期；原输入已保留。", status_code=422)
        if values.get("review_latest") and error.error in {"invalid_request", "currency_not_supported", "amount_invalid"}:
            # A malformed original body cannot become valid by replaying it. Only
            # release it for editing after proving its key has no server result.
            # Accepted/in-flight keys continue through the original receipt path.
            auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
            if funds_request_is_unpublished(db, auth, values.get("idempotency_key", "")):
                return _render(request, db, ledger_id=ledger, task=values.get("mode", ""),
                    account_id=values.get("account_id", ""), values={**values, "idempotency_key": str(uuid4())},
                    error=error.message + " 原提交未记账，请修改保留的输入后确认。", result="prepared",
                    prepared_from=values.get("idempotency_key", ""))
        response = draft_error_response(request, error)
        if response is not None:
            return response
        return _render(request, db, ledger_id=ledger, task=values.get("mode", ""), account_id=values.get("account_id", ""),
            values=values, error=error.message, result=draft_refusal_result(error), status=error.status_code)
    href = funds_result_href(values, ledger, receipt.public_id)
    return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=values["idempotency_key"],
        receipt=receipt, next_href=href) or _web_redirect("/web/funds", ledger, account_id=receipt.public_id)
