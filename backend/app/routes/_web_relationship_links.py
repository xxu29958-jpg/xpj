"""Authorized navigation from a shared split snapshot to its relationship."""

from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.errors import AppError
from app.services.bill_split_service import list_accepted_source_relationships
from app.services.debt_service import (
    get_participant_debt_response,
    participant_accessible_debt_public_ids,
)


def authorized_debt_href(db: Session, *, public_id: str | None, selected_id: str, account_id: int) -> str:
    if not public_id:
        return ""
    try:
        get_participant_debt_response(db, public_id=public_id, ledger_id=selected_id, account_id=account_id)
    except AppError as exc:
        if exc.error == "debt_not_found":
            return ""
        raise
    return f"/web/debts/{public_id}?{urlencode({'ledger_id': selected_id})}"


def accepted_split_debt_links(db: Session, invitations, *, selected_id: str, account_id: int) -> dict[str, str]:
    """Reuse the accepted-source projection, then batch-check its participant fence."""
    accepted = [inv for inv in invitations if inv.status == "accepted"]
    sources = {(inv.sender_ledger_id, inv.sender_expense_id) for inv in accepted}
    visible_ids = {inv.public_id for inv in accepted}
    debt_by_invitation: dict[str, str] = {}
    for ledger_id, expense_id in sources:
        relationships = list_accepted_source_relationships(db, sender_ledger_id=ledger_id, sender_expense_id=expense_id)
        for relationship in relationships:
            if relationship.invitation_public_id in visible_ids and relationship.debt_public_id:
                debt_by_invitation[relationship.invitation_public_id] = relationship.debt_public_id
    accessible_ids = participant_accessible_debt_public_ids(
        db,
        public_ids=set(debt_by_invitation.values()),
        ledger_id=selected_id,
        account_id=account_id,
    )
    return {
        invitation_id: f"/web/debts/{debt_public_id}?{urlencode({'ledger_id': selected_id})}"
        for invitation_id, debt_public_id in debt_by_invitation.items()
        if debt_public_id in accessible_ids
    }
