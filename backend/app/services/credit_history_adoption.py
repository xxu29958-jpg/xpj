"""One reviewed opening replaces the current fold, without replacing the Debt identity."""
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.errors import AppError
from app.models import CreditFacility, Debt
from app.schemas.funds import ExistingDebtChoice
from app.services.ledger_calendar_service import current_calendar
from app.services.time_service import ensure_utc, now_utc


def eligible_debts(ledger_id, actor_account_id):
    return select(Debt).where(Debt.tenant_id == ledger_id, Debt.owner_account_id == actor_account_id,
        Debt.source_type == "manual", Debt.counterparty_type == "external", Debt.direction == "i_owe",
        Debt.status != "voided")


def earliest_opening_date(db, debt):
    calendar = current_calendar(db, ledger_id=debt.tenant_id)
    return ensure_utc(debt.updated_at).astimezone(ZoneInfo(calendar.timezone_name)).date()


def existing_debt_choices(db, *, ledger_id, actor_account_id):
    from app.services.debt_service._fold import compute_remaining
    return [ExistingDebtChoice(public_id=row.public_id, row_version=row.row_version, name=row.counterparty_label,
        remaining_home_minor=compute_remaining(db, row), home_currency_code=row.home_currency_code,
        earliest_opening_date=earliest_opening_date(db, row))
        for row in db.scalars(eligible_debts(ledger_id, actor_account_id).order_by(Debt.id))]


def adopt_existing_debt(db, *, auth, account, payload):
    from app.services.debt_service._fold import compute_remaining_for_write
    reference = payload.existing_debt
    debt = db.scalar(eligible_debts(auth.ledger_id, auth.account_id).where(Debt.public_id == reference.public_id)
        .with_for_update(of=Debt).execution_options(populate_existing=True))
    if debt is None:
        raise AppError("credit_adoption_unavailable", "这笔欠款已接入、已作废或不属于你；原输入已保留，请重新核对。", status_code=409)
    if debt.row_version != reference.expected_row_version:
        raise AppError("state_conflict", "原欠款已有新记录，请核对最新余款和期初依据后继续。", status_code=409)
    if payload.opening_date < earliest_opening_date(db, debt):
        raise AppError("credit_adoption_date_conflict", "期初截止日早于原欠款的最后更新，请核对包含这些记录的最新余额。", status_code=422)
    snapshot = {"source_type": debt.source_type, "source_id": debt.source_id, "debt_kind": debt.debt_kind,
        "row_version": debt.row_version, "remaining_home_minor": compute_remaining_for_write(db, debt),
        "home_currency_code": debt.home_currency_code, "actor_account_id": auth.account_id,
        "opening_date": payload.opening_date.isoformat(), "opening_currency_code": account.currency_code,
        "opening_amount_minor": payload.opening_amount_minor, "source": payload.opening_source,
        "visibility": account.visibility}
    adopted_at = now_utc()
    debt.source_type, debt.source_id, debt.debt_kind = "credit_facility", account.public_id, "revolving"
    debt.row_version += 1
    debt.updated_at = adopted_at
    debt.status = "cleared" if payload.opening_amount_minor <= 0 else "open"
    # Original principal, currency, dates, repayments and public_id remain intact.
    db.add(CreditFacility(account_id=account.id, debt_id=debt.id, adopted_at=adopted_at, adopted_from=snapshot))
    return debt
