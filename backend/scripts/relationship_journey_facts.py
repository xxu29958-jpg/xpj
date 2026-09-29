"""Isolated identities and read-only assertions for the actual relationship journey."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationshipIdentity:
    sender_ledger: str
    receiver_ledger: str
    receiver_account: int
    observer_account: int
    viewer_account: int


def seed_identities(sender_ledger):
    from app.database import SessionLocal
    from app.models import Account, Ledger, LedgerMember
    from app.services.ledger_calendar_service import adopt_ledger_calendar

    with SessionLocal() as db:
        receiver = Account(display_name="往来接收方")
        observer = Account(display_name="无关账本成员")
        viewer = Account(display_name="往来只读成员")
        db.add_all([receiver, observer, viewer])
        db.flush()
        receiver_ledger = "relationship-receiver"
        db.add(Ledger(ledger_id=receiver_ledger, name="接收方私有流水", owner_account_id=receiver.id))
        db.flush()
        adopt_ledger_calendar(db, ledger_id=receiver_ledger, timezone_name="Asia/Shanghai", actor_account_id=receiver.id)
        db.add_all([
            LedgerMember(ledger_id=receiver_ledger, account_id=receiver.id, role="owner"),
            LedgerMember(ledger_id=sender_ledger, account_id=receiver.id, role="member"),
            LedgerMember(ledger_id=receiver_ledger, account_id=observer.id, role="member"),
            LedgerMember(ledger_id=receiver_ledger, account_id=viewer.id, role="viewer"),
        ])
        db.commit()
        return RelationshipIdentity(sender_ledger, receiver_ledger, receiver.id, observer.id, viewer.id)


def pairing_code(ledger_id, account_id):
    from app.database import SessionLocal
    from app.services.identity_service import create_pairing_code

    with SessionLocal() as db:
        return create_pairing_code(db, ledger_id=ledger_id, account_id=account_id, ttl_minutes=60).pairing_code


def facts(identity):
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import (
        BillSplitAgreementChange,
        BillSplitChangeProposal,
        BillSplitInvitation,
        Debt,
        Expense,
        ExpenseOffsetFact,
        Repayment,
    )
    from app.services.bill_split_service import get_bill_split_agreement

    with SessionLocal() as db:
        source = db.scalar(select(Expense).where(Expense.tenant_id == identity.sender_ledger))
        invitation = db.scalar(select(BillSplitInvitation))
        original = db.scalar(select(Debt).where(Debt.source_type == "bill_split"))
        received = db.scalar(select(Expense).where(Expense.tenant_id == identity.receiver_ledger))
        result = {
            "source_id": getattr(source, "id", None), "source_amount": getattr(source, "amount_cents", None),
            "received_id": getattr(received, "id", None), "received_amount": getattr(received, "amount_cents", None),
            "invitation_id": getattr(invitation, "public_id", None),
            "invitation_status": getattr(invitation, "status", None),
            "expenses": db.scalar(select(func.count()).select_from(Expense)),
            "offsets": db.scalar(select(func.count()).select_from(ExpenseOffsetFact)),
            "source_refund": int(db.scalar(select(func.coalesce(func.sum(ExpenseOffsetFact.amount_cents), 0)).where(
                ExpenseOffsetFact.tenant_id == identity.sender_ledger, ExpenseOffsetFact.status == "active"))),
            "repayments": db.scalar(select(func.count()).select_from(Repayment)),
            "return_count": db.scalar(select(func.count()).select_from(Debt).where(Debt.source_type == "bill_split_return")),
            "changes": [{field: getattr(row, field) for field in ("public_id", "new_share_amount_cents",
                "settlement_net_amount_cents", "share_before_amount_cents", "original_debt_id", "return_debt_id")}
                for row in db.scalars(select(BillSplitAgreementChange).order_by(BillSplitAgreementChange.id))],
            "proposals": [{field: getattr(row, field) for field in ("public_id", "status", "reason", "new_share_amount_cents",
                "settlement_net_amount_cents", "original_paid_amount_cents", "return_paid_amount_cents",
                "original_forgiven_amount_cents", "return_forgiven_amount_cents")}
                for row in db.scalars(select(BillSplitChangeProposal).order_by(BillSplitChangeProposal.id))],
        }
        if original:
            assert invitation.sender_expense_id == source.id and invitation.received_expense_id == received.id
            assert invitation.receiver_ledger_id == identity.receiver_ledger and original.source_id == invitation.public_id
            relation = get_bill_split_agreement(db, tenant_id=identity.receiver_ledger,
                actor_account_id=identity.receiver_account, public_id=original.public_id)
            result.update(original_id=original.public_id, original_principal=original.principal_amount_cents,
                agreed_share=relation.agreed_share_amount_cents, original_paid=relation.original_paid_amount_cents,
                return_paid=relation.return_paid_amount_cents, original_forgiven=relation.original_forgiven_amount_cents,
                return_forgiven=relation.return_forgiven_amount_cents, settlement=relation.settlement_net_amount_cents,
                original_remaining=relation.original_debt.remaining_amount_cents,
                return_id=relation.return_debt.public_id if relation.return_debt else None,
                pending_id=relation.pending_proposal.public_id if relation.pending_proposal else None,
                pending_repayments=relation.pending_repayment_debt_public_ids,
                original_version=relation.original_debt.row_version,
                return_version=relation.return_debt.row_version if relation.return_debt else None)
        return result
