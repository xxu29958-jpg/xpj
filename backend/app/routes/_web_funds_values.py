"""Translate retained Web inputs to the existing funds command schemas."""
from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.errors import AppError
from app.routes._web_installments import payment_allocations
from app.schemas.credit_fee import CreditFeeCreate
from app.schemas.funds import (
    AccountCreate,
    AccountEdit,
    AccountPosting,
    CreditPayment,
    CreditTerms,
    DebtAdoption,
    FinancialAccountView,
)
from app.services.currency_common import major_amount_to_minor, minor_amount_value
from app.services.funds_query import get_account
from app.tenants import AuthContext


def form_defaults(account: FinancialAccountView | None, task: str, home_currency: str, today: date,
                  repayment_id: str) -> dict[str, str]:
    values = dict.fromkeys(("account_id", "task_id", "name", "institution", "tail", "opening_amount",
        "expected_row_version", "calendar_revision", "payer_public_id", "payer_row_version", "payer_currency_code",
        "fee_period_id", "payer_fee_amount", "principal_amount", "payer_amount", "note", "activity_amount", "other_amount", "loan_name",
        "loan_principal_amount", "new_fee", "fee_note", "supersedes_public_id", "overpayment", "existing_debt",
        "credit_limit", "available_credit", "credit_observed_on", "credit_source", "statement_day", "payment_due_day"), "")
    values.update(mode=task, kind="bank", currency_code=home_currency, loan_currency_code=home_currency,
        visibility="private", edit_visibility="", opening_source="本人核对", occurred_on=str(today), archived="false", apply_adjustment="false",
        idempotency_key=str(uuid4()), draw_ids_json="[]", periods_json="[]", allocation_json="[]", repayment_public_id=repayment_id)
    if account is not None:
        values.update({name: getattr(account, name) or "" for name in ("name", "kind", "currency_code", "visibility", "institution", "tail")})
        values.update(account_id=account.public_id, task_id=f"{task}:{account.public_id}",
            expected_row_version=str(account.row_version), calendar_revision=str(account.calendar_revision),
            archived=str(account.archived).lower(), loan_currency_code=account.currency_code)
        values.update(_credit_terms_values(account))
    if task == "void_repayment" and repayment_id:
        values["task_id"] += ":" + repayment_id
    return values


def _credit_terms_values(account: FinancialAccountView) -> dict[str, str]:
    terms = account.credit_terms
    if terms is None:
        return {}
    def amount(value: int | None) -> str:
        return minor_amount_value(value, account.currency_code) if value is not None else ""
    return {"credit_limit": amount(terms.credit_limit_minor), "available_credit": amount(terms.available_credit_minor),
        "credit_observed_on": str(terms.observed_on or ""), "credit_source": terms.source or "",
        "statement_day": str(terms.statement_day or ""), "payment_due_day": str(terms.payment_due_day or "")}


def account_create_payload(values: dict[str, str]) -> AccountCreate:
    return AccountCreate(name=values["name"], kind=values["kind"], currency_code=values["currency_code"],
        visibility=values["visibility"], institution=values.get("institution") or None, tail=values.get("tail") or None,
        opening_amount_minor=major_amount_to_minor(values["opening_amount"], values["currency_code"], allow_negative=True)
            if values["opening_amount"].strip() else None,
        opening_date=values["occurred_on"], opening_source=values["opening_source"], existing_debt=_existing_debt(values),
        credit_terms=_credit_terms(values) if values["kind"] == "credit" else None)


def account_edit_payload(values: dict[str, str]) -> AccountEdit:
    payload = AccountEdit(name=values["name"], institution=values.get("institution") or None, tail=values.get("tail") or None,
        archived=values["archived"] == "true", expected_row_version=values["expected_row_version"],
        visibility=values.get("edit_visibility") or None)
    if values.get("kind") == "credit" and "credit_limit" in values:
        payload.credit_terms = _credit_terms(values)
    return payload


def posting_payload(db: Session, auth: AuthContext, values: dict[str, str]) -> AccountPosting:
    mode = values["mode"]
    account = _captured_account(db, auth, values["account_id"], values["currency_code"])
    extras = {}
    if mode == "transfer":
        other = _captured_account(db, auth, values["payer_public_id"], values["payer_currency_code"])
        extras = {"other_account_public_id": other.public_id, "other_account_row_version": int(values["payer_row_version"]),
            "other_amount_minor": major_amount_to_minor(values["other_amount"], other.currency_code)}
    elif mode == "loan":
        extras = {"loan_name": values.get("loan_name") or None, "loan_currency_code": values["loan_currency_code"],
            "loan_principal_minor": major_amount_to_minor(values["loan_principal_amount"], values["loan_currency_code"])}
    amount = major_amount_to_minor(values["activity_amount"], account.currency_code, allow_negative=mode == "reconciliation")
    if mode == "reconciliation" and account.kind == "credit":
        amount = -amount
    return AccountPosting(expected_row_version=values["expected_row_version"], kind=mode, amount_minor=amount,
        occurred_on=values["occurred_on"], note=values["note"], calendar_revision=values["calendar_revision"],
        apply_adjustment=values.get("apply_adjustment") == "true", **extras)


def payment_payload(db: Session, auth: AuthContext, values: dict[str, str]) -> CreditPayment:
    credit = _captured_account(db, auth, values["account_id"], values["currency_code"])
    payer = _captured_account(db, auth, values["payer_public_id"], values["payer_currency_code"])
    return CreditPayment(expected_row_version=values["expected_row_version"], calendar_revision=values["calendar_revision"],
        payer_public_id=payer.public_id, payer_row_version=values["payer_row_version"],
        principal_minor=major_amount_to_minor(values["principal_amount"], credit.currency_code),
        payer_amount_minor=major_amount_to_minor(values["payer_amount"], payer.currency_code),
        occurred_on=values["occurred_on"], note=values["note"],
        new_fee_minor=major_amount_to_minor(values["new_fee"], payer.currency_code) if values.get("new_fee", "").strip() else 0,
        payer_fee_amount_minor=major_amount_to_minor(values["payer_fee_amount"], payer.currency_code) if values.get("payer_fee_amount", "").strip() else 0,
        fee_note=values.get("fee_note") or None, source_repayment_draft_id=values.get("source_repayment_draft_id") or None,
        source_amount_basis=values.get("source_amount_basis") or "payer_total",
        source_review_reason=values.get("source_review_reason") or None, **payment_allocations(values))


def _captured_account(db: Session, auth: AuthContext, public_id: str, currency: str):
    account = get_account(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id, public_id=public_id)
    if account.currency_code != currency:
        raise AppError("state_conflict", "原输入币种与账户不一致，请保留原输入核对后继续。", status_code=409)
    return account


def _existing_debt(values: dict[str, str]) -> DebtAdoption | None:
    value = values.get("existing_debt", "")
    if not value:
        return None
    public_id, version = value.split("|")
    return DebtAdoption(public_id=public_id, expected_row_version=version)


def _credit_terms(values: dict[str, str]) -> CreditTerms:
    def amount(name: str) -> int | None:
        return major_amount_to_minor(values[name], values["currency_code"]) if values.get(name, "").strip() else None
    return CreditTerms(credit_limit_minor=amount("credit_limit"), available_credit_minor=amount("available_credit"),
        observed_on=values.get("credit_observed_on") or None, source=values.get("credit_source") or None,
        statement_day=values.get("statement_day") or None, payment_due_day=values.get("payment_due_day") or None)


def credit_fee_payload(db, auth, values):
    account = _captured_account(db, auth, values["account_id"], values["currency_code"])
    return CreditFeeCreate(expected_row_version=values["expected_row_version"], calendar_revision=values["calendar_revision"],
        amount_minor=major_amount_to_minor(values["activity_amount"], account.currency_code),
        occurred_on=values["occurred_on"], note=values["note"], period_public_id=values.get("fee_period_id") or None)
