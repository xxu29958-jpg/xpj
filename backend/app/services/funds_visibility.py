"""One ledger and ownership boundary for account and credit-obligation reads."""
from sqlalchemy import and_, or_

from app.models import FinancialAccount


def account_scope(ledger_id, actor_account_id):
    return and_(FinancialAccount.tenant_id == ledger_id,
        or_(FinancialAccount.owner_account_id == actor_account_id, FinancialAccount.visibility == "ledger"))
