"""Actual income, loans, paired transfers and explicit balance observations."""
from uuid import uuid4

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import AccountBalanceObservation, CreditFacility, Debt, FinancialAccount
from app.schemas._accounting_time import AccountingTimeInput
from app.schemas.funds import AccountPosting, FinancialAccountReceipt
from app.services.debt_service._repayment_time import resolve_repayment_time
from app.services.funds_commands import claim_funds, finish_funds, movement, replay_funds, require_account_version
from app.services.funds_fact_service import refresh_credit, validate_movement_date
from app.services.funds_money import valuation
from app.services.funds_query import account_balance, get_account
from app.tenants import AuthContext


def post_account_activity(db: Session, *, auth: AuthContext, public_id: str,
        payload: AccountPosting, key: str) -> FinancialAccountReceipt:
    claim = claim_funds(db, auth, payload, key, "post_account_activity", public_id)
    if claim is None:
        return replay_funds(db, auth, key)
    identifiers = {public_id}
    if payload.other_account_public_id:
        identifiers.add(payload.other_account_public_id)
    accounts = {pid: get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id,
        public_id=pid, lock=True) for pid in sorted(identifiers)}
    account = accounts[public_id]
    require_account_version(account, payload.expected_row_version)
    validate_movement_date(db, account, payload.occurred_on)
    time = resolve_repayment_time(db, ledger_id=account.tenant_id, paid_at=None,
        time_input=AccountingTimeInput(precision="date_only", user_local_date=payload.occurred_on,
            calendar_revision=payload.calendar_revision))
    event = str(uuid4())
    if payload.kind == "reconciliation":
        if account.owner_account_id != auth.account_id:
            raise AppError("permission_denied", "期初与外部余额由账户所有者核对。", status_code=403)
        recorded = account_balance(db, account, cutoff=payload.occurred_on)
        observation = AccountBalanceObservation(account_id=account.id, observed_minor=payload.amount_minor,
            recorded_minor=recorded, occurred_on=payload.occurred_on, source=payload.note, actor_account_id=auth.account_id)
        if payload.apply_adjustment:
            adjustment = movement(db, auth, account, event=event, component="adjustment", kind="reconciliation",
                amount=payload.amount_minor - recorded, occurred_on=payload.occurred_on, note=payload.note)
            db.flush()
            observation.adjustment_movement_id = adjustment.id
            account.balance_known = True
        db.add(observation)
    else:
        if account.kind == "credit" or payload.amount_minor <= 0:
            raise AppError("invalid_request", "请选择现金、银行卡或余额账户，并填写正数实际金额。", status_code=422)
        if payload.kind == "transfer":
            _transfer(db, auth, account, accounts.get(payload.other_account_public_id), payload, event)
        elif payload.kind == "income":
            movement(db, auth, account, event=event, component="income", kind="income", amount=payload.amount_minor,
                occurred_on=payload.occurred_on, note=payload.note)
        else:
            _loan(db, auth, account, payload, event, time)
    account.row_version += 1
    refresh_credit(db, account)
    return finish_funds(db, auth, claim, account)


def _transfer(db, auth, account, other, payload, event):
    if other is None or other.id == account.id or other.kind == "credit" or payload.other_amount_minor is None:
        raise AppError("invalid_request", "请选择不同的收款账户并填写实际到账金额；信用本金请使用还款。", status_code=422)
    require_account_version(other, payload.other_account_row_version)
    validate_movement_date(db, other, payload.occurred_on)
    if account.currency_code == other.currency_code and payload.amount_minor != payload.other_amount_minor:
        raise AppError("funding_amount_mismatch", "同币种转账两端金额须相等；已发生费用请单独记录消费。", status_code=422)
    movement(db, auth, account, event=event, component="out", kind="transfer", amount=-payload.amount_minor,
        occurred_on=payload.occurred_on, note=payload.note)
    movement(db, auth, other, event=event, component="in", kind="transfer", amount=payload.other_amount_minor,
        occurred_on=payload.occurred_on, note=payload.note)
    other.row_version += 1


def _loan(db, auth, account, payload, event, time) -> None:
    if not payload.loan_name or not payload.loan_currency_code or not payload.loan_principal_minor:
        raise AppError("invalid_request", "请填写贷款方、义务币种和实际本金；到账金额不能替代贷款本金。", status_code=422)
    home, snapshot = valuation(db, ledger_id=account.tenant_id, currency=payload.loan_currency_code,
        amount_minor=payload.loan_principal_minor, occurred_on=payload.occurred_on, required=True)
    if home <= 0:
        raise AppError("amount_invalid", "请核对贷款本金及币种。", status_code=422)
    loan = FinancialAccount(tenant_id=account.tenant_id, owner_account_id=auth.account_id,
        name=payload.loan_name, kind="credit", currency_code=payload.loan_currency_code,
        visibility=account.visibility, balance_known=True, opening_date=payload.occurred_on, opening_source=payload.note)
    db.add(loan)
    db.flush()
    debt = Debt(tenant_id=account.tenant_id, owner_account_id=auth.account_id, created_by_account_id=auth.account_id,
        direction="i_owe", counterparty_type="external", counterparty_label=payload.loan_name, debt_kind="one_off",
        source_type="credit_facility", source_id=loan.public_id, principal_amount_cents=home,
        home_currency_code=snapshot["home_currency_code"], original_currency_code=loan.currency_code,
        original_amount_minor=payload.loan_principal_minor, accounting_time_snapshot=time.model_dump(mode="json"), status="open")
    db.add(debt)
    db.flush()
    db.add(CreditFacility(account_id=loan.id, debt_id=debt.id))
    movement(db, auth, loan, event=event, component="obligation", kind="loan", amount=-payload.loan_principal_minor,
        home_amount=-home, valuation_snapshot=snapshot, occurred_on=payload.occurred_on, note=payload.note, debt_id=debt.id)
    movement(db, auth, account, event=event, component="received", kind="loan", amount=payload.amount_minor,
        occurred_on=payload.occurred_on, note=payload.note, debt_id=debt.id)
