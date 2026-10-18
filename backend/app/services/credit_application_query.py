"""Available credits, remaining obligations, and the user's retained allocation decisions."""
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.models import AccountMovement, CreditApplicationReview
from app.schemas.credit_application import CreditApplicationChoice, CreditApplicationHistory, CreditApplicationsView
from app.services.credit_allocation_service import active_credit_movements, allocation_totals, application_totals


def credit_application_choices(db, account_id):
    rows = active_credit_movements(db, account_id)
    debits, credits, _ = allocation_totals(db, [row.id for row in rows])
    available, outstanding = {}, {}
    for row in rows:
        used = credits if row.amount_minor > 0 else debits
        remaining = abs(row.amount_minor) - used.get(row.id, 0)
        if remaining > 0:
            (available if row.amount_minor > 0 else outstanding)[row.public_id] = (row, remaining)
    return available, outstanding


def credit_applications_view(db, account_id):
    credit, draw = aliased(AccountMovement), aliased(AccountMovement)
    reviews = list(db.execute(select(CreditApplicationReview, credit.note, draw.note)
        .join(credit, credit.id == CreditApplicationReview.credit_movement_id)
        .join(draw, draw.id == CreditApplicationReview.draw_movement_id)
        .where(CreditApplicationReview.account_id == account_id).order_by(CreditApplicationReview.id.desc())))
    applied = application_totals(db, [row.id for row, _, _ in reviews])
    available, outstanding = credit_application_choices(db, account_id)
    def choices(items):
        return [CreditApplicationChoice(public_id=row.public_id, note=row.note, occurred_on=row.occurred_on,
            remaining_minor=remaining) for row, remaining in sorted(items.values(), key=lambda item: item[0].id)]
    return CreditApplicationsView(credits=choices(available), obligations=choices(outstanding),
        history=[CreditApplicationHistory(public_id=row.public_id, credit_note=credit_note, draw_note=draw_note,
            amount_minor=row.amount_minor, applied_minor=applied.get(row.id, 0), reason=row.reason,
            created_at=row.created_at, void_reason=row.void_reason) for row, credit_note, draw_note in reviews])
