"""Native funds forms use the same commands and retained browser intents as the API."""
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
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
from app.routes._web_installments import installment_form_values, installment_payload, payment_allocations
from app.routes.web_common import (
    LocalOnly,
    _base_ctx,
    _list_ledger_options,
    _require_selected_ledger_write,
    _resolve_selected_ledger_id,
    _web_redirect,
    templates,
)
from app.schemas.funds import (
    AccountCreate,
    AccountEdit,
    AccountPosting,
    CreditPayment,
    CreditPaymentVoid,
    CreditTerms,
    DebtAdoption,
)
from app.services.credit_history_adoption import existing_debt_choices
from app.services.currency_common import major_amount_to_minor, minor_amount_label, supported_currency_codes
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

router = APIRouter(prefix="/web/funds", tags=["web"])


def _scope(request, db, ledger_id):
    options = _list_ledger_options(db)
    selected = _resolve_selected_ledger_id(db, ledger_id or None, options, request=request)
    auth = getattr(request.state, "web_session_auth", None)
    if auth is None or auth.ledger_id != selected:
        raise AppError("invalid_token", "请先登录此浏览器，资金账户按你的身份显示。", status_code=401)
    return options, selected, auth


def _render(request, db, *, ledger_id, task="", account_id="", values=None, error=None, result="", status=200, agreement_id="", repayment_id="", prepared_from=""):
    options, selected, auth = _scope(request, db, ledger_id)
    accounts = list_accounts(db, ledger_id=selected, actor_account_id=auth.account_id)
    account = account_view(db, get_account(db, ledger_id=selected, actor_account_id=auth.account_id,
        public_id=account_id), actor_account_id=auth.account_id, with_movements=True) if account_id else None
    ctx = _base_ctx(request, db=db, options=options, selected_ledger_id=selected, page_title="资金账户")
    defaults = {"mode": task, "account_id": account_id, "task_id": f"{task}:{account_id}" if account_id else "",
        "name": account.name if account else "", "kind": account.kind if account else "bank",
        "currency_code": account.currency_code if account else ctx["home_currency_code"],
        "visibility": account.visibility if account else "private", "institution": (account.institution or "") if account else "",
        "tail": (account.tail or "") if account else "", "opening_amount": "", "opening_source": "本人核对",
        "occurred_on": str(current_ledger_date(db, ledger_id=account.ledger_id if account else selected)),
        "expected_row_version": str(account.row_version) if account else "", "archived": "true" if account and account.archived else "false",
        "calendar_revision": str(account.calendar_revision) if account else "", "payer_public_id": "", "payer_row_version": "",
        "payer_currency_code": "", "principal_amount": "", "payer_amount": "", "note": "",
        "activity_amount": "", "other_amount": "", "apply_adjustment": "false", "loan_name": "",
        "loan_currency_code": account.currency_code if account else ctx["home_currency_code"],
        "loan_principal_amount": "", "new_fee": "", "fee_note": "", "idempotency_key": str(uuid4()),
        "draw_ids_json": "[]", "periods_json": "[]", "supersedes_public_id": "", "allocation_json": "[]", "overpayment": "",
        "repayment_public_id": repayment_id, "existing_debt": ""}
    terms = account.credit_terms if account else None
    def credit_amount(value):
        from app.services.currency_common import minor_amount_value
        return minor_amount_value(value, account.currency_code) if value is not None else ""
    defaults.update(credit_limit=credit_amount(terms.credit_limit_minor) if terms else "",
        available_credit=credit_amount(terms.available_credit_minor) if terms else "",
        credit_observed_on=str(terms.observed_on) if terms and terms.observed_on else "",
        credit_source=terms.source or "" if terms else "",
        statement_day=str(terms.statement_day) if terms and terms.statement_day else "",
        payment_due_day=str(terms.payment_due_day) if terms and terms.payment_due_day else "")
    if task == "void_repayment" and repayment_id:
        defaults["task_id"] = f"void_repayment:{account_id}:{repayment_id}"
    installments = installments_view(db, get_account(db, ledger_id=selected, actor_account_id=auth.account_id,
        public_id=account_id)) if account and account.kind == "credit" else None
    if agreement_id and installments:
        agreement = next((row for row in installments.agreements if row.public_id == agreement_id and row.active), None)
        if agreement is None:
            raise AppError("state_conflict", "合约已更新，请打开当前版本。", status_code=409)
        defaults.update(installment_form_values(agreement, account.currency_code))
        defaults["draw_ids_json"] = json.dumps([row.public_id for row in installments.draws
            if row.public_id in agreement.draw_public_ids and row.remaining_minor > 0])
    ctx.update(accounts=accounts, account=account, task=task, values=defaults if values is None else values,
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


def _run(db, auth, values, payload, handler, operation, review):
    target = values.get("account_id") or None
    if review:
        claimed = claim_funds(db, auth, payload, values["idempotency_key"], operation, target)
        if claimed is None:
            return replay_funds(db, auth, values["idempotency_key"])
        db.rollback()
        return None
    kwargs = {"public_id": target} if target else {}
    return handler(db, auth=auth, payload=payload, key=values["idempotency_key"], **kwargs)


def _execute(db, auth, values, *, review=False):
    mode = values["mode"]
    if mode == "void_repayment":
        payload = CreditPaymentVoid(expected_row_version=values["expected_row_version"],
            repayment_public_id=values["repayment_public_id"], occurred_on=values["occurred_on"], reason=values["note"])
        return _run(db, auth, values, payload, void_credit_payment, "void_credit_payment", review)
    if mode == "installments":
        account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=values["account_id"])
        if account.currency_code != values["currency_code"]:
            raise AppError("state_conflict", "原合约币种已变化，请保留原输入核对。", status_code=409)
        return _run(db, auth, values, installment_payload(values), save_installments, "save_installment_agreement", review)
    if mode == "create":
        payload = AccountCreate(name=values["name"], kind=values["kind"], currency_code=values["currency_code"],
            visibility=values["visibility"], institution=values.get("institution") or None, tail=values.get("tail") or None,
            opening_amount_minor=major_amount_to_minor(values["opening_amount"], values["currency_code"], allow_negative=True)
                if values["opening_amount"].strip() else None,
            opening_date=values["occurred_on"], opening_source=values["opening_source"],
            existing_debt=_existing_debt(values))
        payload.credit_terms = _credit_terms(values) if payload.kind == "credit" else None
        return _run(db, auth, values, payload, create_account, "create_financial_account", review)
    if mode == "edit":
        payload = AccountEdit(name=values["name"], institution=values.get("institution") or None, tail=values.get("tail") or None,
            archived=values["archived"] == "true", expected_row_version=values["expected_row_version"])
        if values.get("kind") == "credit" and "credit_limit" in values:
            payload.credit_terms = _credit_terms(values)
        return _run(db, auth, values, payload, edit_account, "edit_financial_account", review)
    if mode in {"income", "loan", "transfer", "reconciliation"}:
        account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=values["account_id"])
        if account.currency_code != values["currency_code"]:
            raise AppError("state_conflict", "原输入币种与账户不一致，请核对后继续。", status_code=409)
        if mode == "transfer":
            other = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=values["payer_public_id"])
            if other.currency_code != values["payer_currency_code"]:
                raise AppError("state_conflict", "原收款币种与账户不一致，请核对后继续。", status_code=409)
        payload = AccountPosting(expected_row_version=values["expected_row_version"], kind=mode,
            amount_minor=major_amount_to_minor(values["activity_amount"], account.currency_code, allow_negative=mode == "reconciliation") *
                (-1 if mode == "reconciliation" and account.kind == "credit" else 1),
            occurred_on=values["occurred_on"], note=values["note"], calendar_revision=values["calendar_revision"],
            other_account_public_id=values["payer_public_id"] if mode == "transfer" else None,
            other_account_row_version=int(values["payer_row_version"]) if mode == "transfer" else None,
            other_amount_minor=major_amount_to_minor(values["other_amount"], values["payer_currency_code"]) if mode == "transfer" else None,
            apply_adjustment=values.get("apply_adjustment") == "true", loan_name=values.get("loan_name") or None,
            loan_currency_code=values["loan_currency_code"] if mode == "loan" else None,
            loan_principal_minor=major_amount_to_minor(values["loan_principal_amount"], values["loan_currency_code"]) if mode == "loan" else None)
        return _run(db, auth, values, payload, post_account_activity, "post_account_activity", review)
    if mode != "repay":
        raise AppError("invalid_request", "请选择要办理的资金事项。", status_code=422)
    # The captured currencies must still match the authoritative accounts. Never reinterpret a retained amount.
    credit = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=values["account_id"])
    payer = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=values["payer_public_id"])
    if credit.currency_code != values["currency_code"] or payer.currency_code != values["payer_currency_code"]:
        raise AppError("state_conflict", "原输入币种与账户不一致，请核对后继续。", status_code=409)
    payload = CreditPayment(expected_row_version=values["expected_row_version"], calendar_revision=values["calendar_revision"],
        payer_public_id=payer.public_id, payer_row_version=values["payer_row_version"],
        principal_minor=major_amount_to_minor(values["principal_amount"], credit.currency_code),
        payer_amount_minor=major_amount_to_minor(values["payer_amount"], payer.currency_code),
        occurred_on=values["occurred_on"], note=values["note"],
        new_fee_minor=major_amount_to_minor(values["new_fee"], payer.currency_code) if values.get("new_fee", "").strip() else 0,
        fee_note=values.get("fee_note") or None, **payment_allocations(values))
    return _run(db, auth, values, payload, pay_credit, "pay_credit_from_account", review)


def _existing_debt(values):
    value = values.get("existing_debt", "")
    if not value:
        return None
    public_id, version = value.split("|")
    return DebtAdoption(public_id=public_id, expected_row_version=version)


def _credit_terms(values):
    def amount(name):
        return major_amount_to_minor(values[name], values["currency_code"]) if values.get(name, "").strip() else None
    return CreditTerms(credit_limit_minor=amount("credit_limit"), available_credit_minor=amount("available_credit"),
        observed_on=values.get("credit_observed_on") or None, source=values.get("credit_source") or None,
        statement_day=values.get("statement_day") or None, payment_due_day=values.get("payment_due_day") or None)


@router.post("/save")
async def web_save_funds(request: Request, _local: None = LocalOnly, db: Session = Depends(get_db)):
    values = dict(await request.form())
    ledger = str(values.get("ledger_id", ""))
    try:
        auth = require_draft_binding(db, request, ledger_id=ledger, draft_scope=values.get("draft_scope", ""))
        _require_selected_ledger_write(_list_ledger_options(db), ledger)
        if values.get("review_latest"):
            original = _execute(db, auth, values, review=True)
            if original is not None:
                href = f"/web/funds?ledger_id={ledger}&account_id={original.public_id}"
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
    href = f"/web/funds?ledger_id={ledger}&account_id={receipt.public_id}"
    return draft_ack_response(request, draft_scope=values["draft_scope"], idempotency_key=values["idempotency_key"],
        receipt=receipt, next_href=href) or _web_redirect("/web/funds", ledger, account_id=receipt.public_id)
