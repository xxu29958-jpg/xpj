"""Authorized navigation from a shared split snapshot to its relationship."""

from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.services.bill_split_service import list_accepted_source_relationships
from app.services.debt_service import participant_accessible_debt_public_ids


def authorized_debt_hrefs(db: Session, *, public_ids: set[str], selected_id: str, account_id: int) -> dict[str, str]:
    accessible_ids = participant_accessible_debt_public_ids(
        db, public_ids=public_ids, ledger_id=selected_id, account_id=account_id,
    )
    return {
        public_id: f"/web/debts/{public_id}?{urlencode({'ledger_id': selected_id})}"
        for public_id in accessible_ids
    }


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
    links = authorized_debt_hrefs(
        db, public_ids=set(debt_by_invitation.values()), selected_id=selected_id, account_id=account_id,
    )
    return {
        invitation_id: links[debt_public_id]
        for invitation_id, debt_public_id in debt_by_invitation.items()
        if debt_public_id in links
    }
