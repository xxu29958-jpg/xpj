"""Funds facts in the existing portable snapshot, with the same account visibility."""

from collections.abc import Callable

from sqlalchemy import Select, and_, case, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app import models as m
from app.database_model_registry import Base
from app.services.funds_query import account_scope
from app.tenants import AuthContext

FUNDS_COLLECTION_SCOPES = {
    **dict.fromkeys(("financial_accounts", "credit_facilities", "expense_funding", "account_movements",
        "credit_settlement_allocations", "credit_application_reviews", "account_balance_observations", "installment_agreements",
        "credit_fee_obligations", "installment_draws", "installment_periods", "installment_payments", "envelope_books",
        "envelope_sources", "envelope_allocations", "envelope_revisions"), "ledger"),
    "payment_captures": "account",
}


def fund_account_ids(auth: AuthContext) -> Select:
    # An export is for the selected ledger, including archived records. Membership
    # still does not grant another member's private financial account.
    return select(m.FinancialAccount.id).where(m.FinancialAccount.tenant_id == auth.ledger_id,
        account_scope(auth.ledger_id, auth.account_id))


def funds_receipts_allowed(auth: AuthContext) -> ColumnElement[bool]:
    receipt = m.ApiIdempotencyKey
    accounts = select(m.FinancialAccount.public_id).where(m.FinancialAccount.id.in_(fund_account_ids(auth)))
    captures = select(m.PaymentCapture.public_id).where(m.PaymentCapture.tenant_id == auth.ledger_id,
        m.PaymentCapture.actor_account_id == auth.account_id)
    return or_(and_(receipt.resource_type == "financial_account", receipt.resource_id.in_(accounts)),
        and_(receipt.resource_type == "payment_capture", receipt.resource_id.in_(captures)),
        and_(receipt.resource_type == "envelope_book", receipt.resource_id == auth.ledger_id))


def private_funding_receipt(auth: AuthContext) -> ColumnElement[bool]:
    receipt, funding = m.ApiIdempotencyKey, m.ExpenseFunding
    visible = select(m.FinancialAccount.id).where(account_scope(auth.ledger_id, auth.account_id))
    hidden_part = select(funding.id).where(funding.tenant_id == auth.ledger_id,
        funding.expense_id == receipt.response_body["expense_id"].as_integer(),
        funding.expense_row_version == receipt.response_body["expense_row_version"].as_integer(),
        funding.account_id.not_in(visible)).exists()
    return and_(receipt.operation == "save_expense_funding", hidden_part)


def funds_queries(auth: AuthContext, record: Callable[[type[Base], str, ColumnElement[bool]], Select]
                  ) -> tuple[tuple[str, Select], ...]:
    accounts = fund_account_ids(auth)
    movements = select(m.AccountMovement.id).where(m.AccountMovement.account_id.in_(accounts))
    agreements = select(m.InstallmentAgreement.id).where(m.InstallmentAgreement.account_id.in_(accounts))
    periods = select(m.InstallmentPeriod.id).where(m.InstallmentPeriod.agreement_id.in_(agreements))
    inventory = (
        (m.FinancialAccount, "id public_id tenant_id owner_account_id name kind currency_code visibility institution tail "
            "credit_limit_minor available_credit_minor credit_observed_on credit_source statement_day payment_due_day "
            "balance_known opening_date opening_source archived_at row_version created_at", m.FinancialAccount.id.in_(accounts)),
        (m.CreditFacility, "id account_id debt_id adopted_at adopted_from", m.CreditFacility.account_id.in_(accounts)),
        (m.AccountMovement, "id public_id tenant_id account_id event_public_id component_id kind amount_minor home_amount_cents "
            "home_currency_code valuation_snapshot settlement_targets occurred_on note actor_account_id funding_id repayment_id "
            "offset_id debt_id reversal_of_id created_at", m.AccountMovement.id.in_(movements)),
        (m.CreditSettlementAllocation, "id repayment_id review_id credit_movement_id draw_movement_id amount_minor home_amount_cents "
            "invalidated_by_movement_id created_at", and_(m.CreditSettlementAllocation.credit_movement_id.in_(movements),
            m.CreditSettlementAllocation.draw_movement_id.in_(movements))),
        (m.CreditApplicationReview, "id public_id account_id credit_movement_id draw_movement_id amount_minor reason "
            "actor_account_id created_at voided_at void_reason void_actor_account_id", m.CreditApplicationReview.account_id.in_(accounts)),
        (m.AccountBalanceObservation, "id account_id observed_minor recorded_minor occurred_on source adjustment_movement_id "
            "actor_account_id created_at", m.AccountBalanceObservation.account_id.in_(accounts)),
        (m.CreditFeeObligation, "expense_id account_id period_id", m.CreditFeeObligation.account_id.in_(accounts)),
        (m.InstallmentAgreement, "id public_id account_id series_id revision supersedes_id name source agreed_on actor_account_id created_at",
            m.InstallmentAgreement.id.in_(agreements)),
        (m.InstallmentDraw, "id agreement_id movement_id principal_minor", m.InstallmentDraw.agreement_id.in_(agreements)),
        (m.InstallmentPeriod, "id public_id agreement_id position due_on principal_minor planned_fee_minor", m.InstallmentPeriod.id.in_(periods)),
        (m.InstallmentPayment, "id period_id repayment_id principal_minor fee_minor fee_expense_id created_at", m.InstallmentPayment.period_id.in_(periods)),
        (m.EnvelopeBook, "tenant_id home_currency_code row_version updated_at", m.EnvelopeBook.tenant_id == auth.ledger_id),
        (m.EnvelopeSource, "account_id tenant_id", and_(m.EnvelopeSource.tenant_id == auth.ledger_id, m.EnvelopeSource.account_id.in_(accounts))),
        (m.EnvelopeAllocation, "tenant_id month purpose allocated_minor", m.EnvelopeAllocation.tenant_id == auth.ledger_id),
        (m.EnvelopeRevision, "tenant_id row_version actor_account_id month reason allocation_snapshot recorded_at", m.EnvelopeRevision.tenant_id == auth.ledger_id),
        (m.PaymentCapture, "id public_id tenant_id actor_account_id identity_hash source captured_at original_currency original_amount_minor "
            "merchant parser_version candidates kind expense_public_id repayment_public_id decisions row_version created_at",
            and_(m.PaymentCapture.tenant_id == auth.ledger_id, m.PaymentCapture.actor_account_id == auth.account_id)),
    )
    return (*((model.__tablename__, record(model, fields, scope)) for model, fields, scope in inventory),
        ("expense_funding", _funding_query(auth, record)))


def _funding_query(auth: AuthContext, record: Callable[[type[Base], str, ColumnElement[bool]], Select]) -> Select:
    funding = m.ExpenseFunding
    # Keep the shared purchase's source component and history while withholding
    # the private account reference, currency amount and account-level balance.
    visible = funding.account_id.in_(select(m.FinancialAccount.id).where(account_scope(auth.ledger_id, auth.account_id)))
    return record(funding, "id tenant_id expense_id component_id expense_amount_minor expense_row_version actor_account_id "
        "included_in_opening voided_at void_reason created_at", funding.tenant_id == auth.ledger_id).add_columns(
        case((visible, funding.account_id), else_=None).label("account_id"),
        case((visible, funding.account_amount_minor), else_=None).label("account_amount_minor"),
        case((visible, None), else_="private_account").label("account_redaction_reason"))
