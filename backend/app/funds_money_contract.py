"""Current funds facts extend the frozen historical money manifest."""
from app.money_contract_types import MoneyColumn, MoneySign

FUNDS_MONEY_COLUMNS = (
    MoneyColumn("credit_application_reviews", "amount_minor", MoneySign.POSITIVE, False),
    MoneyColumn("envelope_allocations", "allocated_minor", MoneySign.NONNEGATIVE, False),
    MoneyColumn("financial_accounts", "credit_limit_minor", MoneySign.NONNEGATIVE, True),
    MoneyColumn("financial_accounts", "available_credit_minor", MoneySign.NONNEGATIVE, True),
    MoneyColumn("installment_draws", "principal_minor", MoneySign.POSITIVE, False),
    MoneyColumn("installment_periods", "principal_minor", MoneySign.NONNEGATIVE, False),
    MoneyColumn("installment_periods", "planned_fee_minor", MoneySign.NONNEGATIVE, False),
    MoneyColumn("installment_payments", "principal_minor", MoneySign.NONNEGATIVE, False),
    MoneyColumn("installment_payments", "fee_minor", MoneySign.NONNEGATIVE, False),
    MoneyColumn("account_balance_observations", "observed_minor", MoneySign.SIGNED, False),
    MoneyColumn("account_balance_observations", "recorded_minor", MoneySign.SIGNED, False),
    MoneyColumn("expense_funding", "expense_amount_minor", MoneySign.POSITIVE, False),
    MoneyColumn("expense_funding", "account_amount_minor", MoneySign.POSITIVE, False),
    MoneyColumn("account_movements", "amount_minor", MoneySign.SIGNED, False),
    MoneyColumn("account_movements", "home_amount_cents", MoneySign.SIGNED, True),
    MoneyColumn("credit_settlement_allocations", "amount_minor", MoneySign.POSITIVE, False),
    MoneyColumn("credit_settlement_allocations", "home_amount_cents", MoneySign.NONNEGATIVE, True),
)
CREDIT_DEBT_MONEY_COLUMNS = (
    MoneyColumn("repayments", "amount_cents", MoneySign.NONNEGATIVE, False,
        final_predicate_override="amount_cents BETWEEN 0 AND 9000000000000 AND (settlement_kind = 'credit' OR amount_cents > 0)"),
    MoneyColumn("repayments", "original_amount_minor", MoneySign.NONNEGATIVE, True,
        final_predicate_override="original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000 AND (settlement_kind = 'credit' OR original_amount_minor > 0))"),
    MoneyColumn("debts", "principal_amount_cents", MoneySign.NONNEGATIVE, False,
        final_predicate_override="principal_amount_cents BETWEEN 0 AND 9000000000000 AND (source_type = 'credit_facility' OR principal_amount_cents > 0)"),
    MoneyColumn("debts", "original_amount_minor", MoneySign.NONNEGATIVE, True,
        final_predicate_override="original_amount_minor IS NULL OR (original_amount_minor BETWEEN 0 AND 9000000000000 AND (source_type = 'credit_facility' OR original_amount_minor > 0))"),
)
