"""Frozen bilateral split-change proposals and append-only accepted agreements."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DDL, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.money_contract_types import MONEY_AGGREGATE_MAX, MONEY_MINOR_MAX
from app.services.time_service import now_utc


class BillSplitChangeProposal(Base):
    __tablename__ = "bill_split_change_proposals"
    __table_args__ = (
        *(CheckConstraint(f"{name} BETWEEN 0 AND {MONEY_MINOR_MAX}", name=f"ck_bscp_{name}")
          for name in ("share_before_amount_cents", "new_share_amount_cents")),
        CheckConstraint(f"settlement_net_amount_cents BETWEEN {-MONEY_MINOR_MAX} AND {MONEY_MINOR_MAX}",
                        name="ck_bscp_settlement_net_amount_cents"),
        *(CheckConstraint(f"{name} BETWEEN 0 AND {MONEY_AGGREGATE_MAX}", name=f"ck_bscp_{name}")
          for name in ("original_paid_amount_cents", "return_paid_amount_cents",
                       "original_forgiven_amount_cents", "return_forgiven_amount_cents")),
        CheckConstraint(f"settlement_before_net_amount_cents BETWEEN {-MONEY_AGGREGATE_MAX} AND {MONEY_AGGREGATE_MAX}",
                        name="ck_bscp_settlement_before_net_amount_cents"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'withdrawn', 'superseded', 'expired')",
                        name="ck_bscp_status"),
        CheckConstraint("original_debt_row_version >= 1", name="ck_bscp_original_version"),
        CheckConstraint("(return_debt_id IS NULL AND return_debt_row_version IS NULL) OR "
                        "(return_debt_id IS NOT NULL AND return_debt_row_version IS NOT NULL "
                        "AND return_debt_row_version >= 1 AND return_debt_id <> original_debt_id)",
                        name="ck_bscp_return_version"),
        CheckConstraint("(status = 'pending' AND resolved_at IS NULL AND resolved_by_account_id IS NULL) OR "
                        "(status <> 'pending' AND resolved_at IS NOT NULL)", name="ck_bscp_resolution"),
        CheckConstraint("length(trim(reason)) BETWEEN 1 AND 500", name="ck_bscp_reason"),
        CheckConstraint("expires_at > created_at", name="ck_bscp_expiry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("bill_split_invitations.id", ondelete="RESTRICT"), nullable=False)
    proposed_by_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    original_debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id", ondelete="RESTRICT"), nullable=False)
    original_debt_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    return_debt_id: Mapped[int | None] = mapped_column(ForeignKey("debts.id", ondelete="RESTRICT"), nullable=True)
    return_debt_row_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    share_before_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_share_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_net_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_before_net_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_paid_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    return_paid_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_forgiven_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    return_forgiven_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True)


class BillSplitAgreementChange(Base):
    __tablename__ = "bill_split_agreement_changes"
    __table_args__ = (
        *(CheckConstraint(f"{name} BETWEEN 0 AND {MONEY_MINOR_MAX}", name=f"ck_bsac_{name}")
          for name in ("share_before_amount_cents", "new_share_amount_cents")),
        CheckConstraint(f"settlement_net_amount_cents BETWEEN {-MONEY_MINOR_MAX} AND {MONEY_MINOR_MAX}",
                        name="ck_bsac_settlement_net_amount_cents"),
        CheckConstraint("return_debt_id IS NULL OR return_debt_id <> original_debt_id", name="ck_bsac_distinct_debts"),
        CheckConstraint("return_adjustment_id IS NULL OR return_debt_id IS NOT NULL", name="ck_bsac_return_adjustment"),
        CheckConstraint("proposed_by_account_id <> accepted_by_account_id", name="ck_bsac_two_parties"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("bill_split_change_proposals.id", ondelete="RESTRICT"),
                                             nullable=False, unique=True)
    invitation_id: Mapped[int] = mapped_column(ForeignKey("bill_split_invitations.id", ondelete="RESTRICT"), nullable=False)
    share_before_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_share_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_net_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    original_debt_id: Mapped[int] = mapped_column(ForeignKey("debts.id", ondelete="RESTRICT"), nullable=False)
    return_debt_id: Mapped[int | None] = mapped_column(ForeignKey("debts.id", ondelete="RESTRICT"), nullable=True)
    original_adjustment_id: Mapped[int | None] = mapped_column(ForeignKey("debt_adjustments.id", ondelete="RESTRICT"), nullable=True)
    return_adjustment_id: Mapped[int | None] = mapped_column(ForeignKey("debt_adjustments.id", ondelete="RESTRICT"), nullable=True)
    proposed_by_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    accepted_by_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("uq_bscp_one_pending_per_invitation", BillSplitChangeProposal.invitation_id, unique=True,
      postgresql_where=BillSplitChangeProposal.status == "pending")
Index("ix_bscp_invitation_created", BillSplitChangeProposal.invitation_id, BillSplitChangeProposal.created_at)
Index("ix_bsac_invitation_created", BillSplitAgreementChange.invitation_id, BillSplitAgreementChange.created_at)

_PROPOSAL_IMMUTABLE_SQL = """
CREATE OR REPLACE FUNCTION ticketbox_split_proposal_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'split proposal evidence is immutable' USING ERRCODE = '55000';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status', 'resolved_at', 'resolved_by_account_id'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'resolved_at', 'resolved_by_account_id'])
       OR (OLD.status <> 'pending' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) THEN
        RAISE EXCEPTION 'split proposal evidence is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_split_proposal_immutable BEFORE UPDATE OR DELETE ON bill_split_change_proposals
FOR EACH ROW EXECUTE FUNCTION ticketbox_split_proposal_immutable();
"""
_CHANGE_IMMUTABLE_SQL = """
CREATE OR REPLACE FUNCTION ticketbox_split_agreement_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
    RAISE EXCEPTION 'split agreement changes are append-only' USING ERRCODE = '55000';
END $$;
CREATE TRIGGER trg_split_agreement_immutable BEFORE UPDATE OR DELETE ON bill_split_agreement_changes
FOR EACH ROW EXECUTE FUNCTION ticketbox_split_agreement_immutable();
"""
event.listen(BillSplitChangeProposal.__table__, "after_create", DDL(_PROPOSAL_IMMUTABLE_SQL).execute_if(dialect="postgresql"))
event.listen(BillSplitAgreementChange.__table__, "after_create", DDL(_CHANGE_IMMUTABLE_SQL).execute_if(dialect="postgresql"))
