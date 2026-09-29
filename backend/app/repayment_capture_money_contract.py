"""Current capture storage; the historical C07 manifest remains frozen."""

from app.money_contract_types import MoneyColumn, MoneySign

REPAYMENT_CAPTURE_MONEY_COLUMNS = (
    MoneyColumn("repayment_drafts", "amount_cents", MoneySign.POSITIVE, True),
    MoneyColumn("repayment_drafts", "original_amount_minor", MoneySign.POSITIVE, True),
)
