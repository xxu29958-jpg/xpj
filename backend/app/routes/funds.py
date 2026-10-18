"""Authenticated funds adapters; all writes publish through one application command."""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.auth import get_current_app_context, get_current_writer_context
from app.database import get_db
from app.schemas.credit_application import CreditApplicationCreate, CreditApplicationVoid
from app.schemas.credit_fee import CreditFeeCreate
from app.schemas.funds import (
    AccountChoice,
    AccountCreate,
    AccountEdit,
    AccountPosting,
    CreditPayment,
    CreditPaymentVoid,
    ExistingDebtChoice,
    ExpenseFundingCommand,
    ExpenseFundingView,
    FinancialAccountView,
    FundsOverview,
)
from app.schemas.installment import InstallmentCommand, InstallmentsView
from app.services.credit_application_commands import apply_retained_credit, void_credit_application
from app.services.credit_fee_commands import incur_credit_fee
from app.services.credit_history_adoption import existing_debt_choices
from app.services.expense_funding_command import expense_funding_view, save_expense_funding
from app.services.funds_account_choices import ACCOUNT_CHOICES
from app.services.funds_commands import create_account, edit_account
from app.services.funds_credit_payment import pay_credit
from app.services.funds_payment_correction import void_credit_payment
from app.services.funds_posting_service import post_account_activity
from app.services.funds_query import account_view, funds_overview, get_account, list_accounts
from app.services.installment_commands import save_installments
from app.services.installment_query import installments_view
from app.tenants import AuthContext

router = APIRouter(prefix="/api/funds/accounts", tags=["funds"])
expense_router = APIRouter(prefix="/api/expenses", tags=["funds"])


@router.get("/templates/list", response_model=list[AccountChoice])
def get_account_choices(auth: AuthContext = Depends(get_current_app_context)):
    return ACCOUNT_CHOICES


@router.get("/existing-debts/list", response_model=list[ExistingDebtChoice])
def get_existing_debts(auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return existing_debt_choices(db, ledger_id=auth.ledger_id, actor_account_id=auth.account_id)


@router.get("/{public_id}/installments", response_model=InstallmentsView)
def get_installments(public_id: str, auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    account = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id)
    return installments_view(db, account)


@router.post("/{public_id}/installments", response_model=FinancialAccountView)
def post_installments(public_id: str, payload: InstallmentCommand, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return save_installments(db, auth=auth, public_id=public_id, payload=payload, key=key)


@expense_router.get("/{expense_id}/funding", response_model=ExpenseFundingView)
def get_expense_funding(expense_id: int, auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return expense_funding_view(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, expense_id=expense_id)


@expense_router.post("/{expense_id}/funding", response_model=ExpenseFundingView)
def post_expense_funding(expense_id: int, payload: ExpenseFundingCommand, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return save_expense_funding(db, auth=auth, expense_id=expense_id, payload=payload, key=key)


@router.get("", response_model=list[FinancialAccountView])
def get_accounts(auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return list_accounts(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id)


@router.get("/{public_id}", response_model=FinancialAccountView)
def get_account_details(public_id: str, auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    row = get_account(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id, public_id=public_id)
    return account_view(db, row, actor_account_id=auth.account_id, with_movements=True)


@router.get("/summary/net-worth", response_model=FundsOverview)
def get_funds_overview(auth: AuthContext = Depends(get_current_app_context), db: Session = Depends(get_db)):
    return funds_overview(db, ledger_id=auth.tenant_id, actor_account_id=auth.account_id)


@router.post("", response_model=FinancialAccountView)
def post_account(payload: AccountCreate, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return create_account(db, auth=auth, payload=payload, key=key)


@router.patch("/{public_id}", response_model=FinancialAccountView)
def patch_account(public_id: str, payload: AccountEdit, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return edit_account(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/repay", response_model=FinancialAccountView)
def post_credit_payment(public_id: str, payload: CreditPayment, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return pay_credit(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/activities", response_model=FinancialAccountView)
def post_funds_activity(public_id: str, payload: AccountPosting, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return post_account_activity(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/repayments/void", response_model=FinancialAccountView)
def post_credit_payment_void(public_id: str, payload: CreditPaymentVoid, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return void_credit_payment(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/fees", response_model=FinancialAccountView)
def post_credit_fee(public_id: str, payload: CreditFeeCreate, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return incur_credit_fee(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/credit-applications", response_model=FinancialAccountView)
def post_credit_application(public_id: str, payload: CreditApplicationCreate, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return apply_retained_credit(db, auth=auth, public_id=public_id, payload=payload, key=key)


@router.post("/{public_id}/credit-applications/void", response_model=FinancialAccountView)
def post_credit_application_void(public_id: str, payload: CreditApplicationVoid, key: str = Header(alias="Idempotency-Key"),
        auth: AuthContext = Depends(get_current_writer_context), db: Session = Depends(get_db)):
    return void_credit_application(db, auth=auth, public_id=public_id, payload=payload, key=key)
