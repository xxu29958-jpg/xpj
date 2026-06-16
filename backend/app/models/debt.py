"""ADR-0049 Debt domain: one frozen obligation plus append-only facts.

Slice 1 (backend groundwork) models the parent ``Debt`` row and the four
append-only fact tables (``Repayment`` / ``DebtAdjustment`` / ``RepaymentVoid``
/ ``DebtVoid``). The fact tables are CREATED empty here — slice 1 only reads
them for the ``remaining`` / ``paid`` fold (§2); the repayment / adjustment /
void *writes* (and the §2.1 parent-row serialization they require) land in
slice 2.

Money is home-currency minor units (``principal_amount_cents`` and every fact
``amount_cents``; §2.2). A foreign-currency Debt freezes a backend-authoritative
home principal at creation via [[0027]] and keeps the original-currency fields
as provenance/display only. ``remaining`` / ``paid`` are derived, never stored
as truth (§2 / §10). ``row_version`` is the [[0041]] OCC token that slice 2's
fold-changing writes serialize on; a brand-new Debt inserts at ``1`` and is not
hand-bumped ([[0041]]).

Slice 3 (member repayment proposal) adds ``MemberRepaymentProposal`` — the
debtor-side "I paid" pending intent for a ``counterparty_type='member'`` Debt
(§3.2 / §5.2 / F5). A proposal is NOT a fact: it never enters the §2 fold while
``pending``. The creditor confirms (full or partial) to commit one ``Repayment``
linked via ``proposal_id``, rejects, or the debtor withdraws; a new proposal
supersedes the existing pending one. The ``uq_mrp_one_pending_per_debt`` partial
UNIQUE index (``WHERE status = 'pending'``) is the §3.2 one-pending-per-Debt
concurrency backstop — service-level supersede is only a workflow convenience.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class Debt(Base):
    """One obligation. Principal is frozen at creation; see ADR-0049 §2."""

    __tablename__ = "debts"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('i_owe', 'owed_to_me')",
            name="ck_debts_direction_valid",
        ),
        CheckConstraint(
            "counterparty_type IN ('member', 'external')",
            name="ck_debts_counterparty_type_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'cleared', 'voided')",
            name="ck_debts_status_valid",
        ),
        CheckConstraint(
            "source_type IN ('manual', 'bill_split')",
            name="ck_debts_source_type_valid",
        ),
        CheckConstraint("principal_amount_cents > 0", name="ck_debts_principal_positive"),
        CheckConstraint("length(home_currency_code) = 3", name="ck_debts_home_currency_format"),
        # §10 hard constraint: a bill-split-sourced Debt is unique per
        # (source_type, source_id) so re-accepting an invitation cannot create
        # a second Debt (§4). source_id is NULL for manual Debt — a composite
        # UNIQUE treats NULLs as distinct on PostgreSQL, so manual rows never
        # collide here.
        UniqueConstraint("source_type", "source_id", name="uq_debts_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_debts_tenant_ledger"),
        nullable=False,
        index=True,
    )
    owner_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_debts_owner_account"), nullable=False, index=True
    )
    created_by_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_debts_created_by_account"), nullable=False
    )

    # --- counterparty (one of member account / external label) ---------------
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    counterparty_type: Mapped[str] = mapped_column(String(16), nullable=False)
    counterparty_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_debts_counterparty_account"), nullable=True
    )
    counterparty_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- money: frozen home principal + original-currency provenance ---------
    principal_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    original_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_rate_to_cny = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- lifecycle + source --------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041 OCC token; ADR-0049 §2.1 fold serialization point (slice 2 writes).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )


Index("ix_debts_tenant_status", Debt.tenant_id, Debt.status)
Index("ix_debts_tenant_owner_direction", Debt.tenant_id, Debt.owner_account_id, Debt.direction)
Index("ix_debts_tenant_public_id", Debt.tenant_id, Debt.public_id)


class Repayment(Base):
    """Append-only committed repayment fact; see ADR-0049 §3.1.

    Slice 1 creates this table empty for the fold to read. Inserts (and the
    §2.1 parent-Debt serialization + overpayment check) land in slice 2.
    """

    __tablename__ = "repayments"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_repayments_amount_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    debt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("debts.id", name="fk_repayments_debt"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    original_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_rate_to_cny = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_repayments_actor_account"), nullable=False
    )
    proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_repayments_debt_created", Repayment.debt_id, Repayment.created_at)


class DebtAdjustment(Base):
    """Append-only signed principal-like correction fact; see ADR-0049 §3.3.

    Slice 1 creates this table empty for the fold to read. Inserts land in
    slice 2 (signed ``amount_cents`` can raise or lower ``remaining``).
    """

    __tablename__ = "debt_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    debt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("debts.id", name="fk_debt_adjustments_debt"), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_debt_adjustments_actor_account"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_debt_adjustments_debt_created", DebtAdjustment.debt_id, DebtAdjustment.created_at)


class RepaymentVoid(Base):
    """Append-only undo of a mistaken repayment; see ADR-0049 §3.4.

    Slice 1 creates this table empty for the fold to read. A repayment may be
    voided at most once (``repayment_id`` UNIQUE). Inserts land in slice 2.
    """

    __tablename__ = "repayment_voids"
    __table_args__ = (
        UniqueConstraint("repayment_id", name="uq_repayment_voids_repayment"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    repayment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("repayments.id", name="fk_repayment_voids_repayment"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_repayment_voids_actor_account"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DebtVoid(Base):
    """Append-only void of an entire Debt; see ADR-0049 §3.5.

    Slice 1 creates this table empty for the fold to read. Inserts (and the
    §2.1 parent-Debt serialization) land in slice 2.
    """

    __tablename__ = "debt_voids"
    __table_args__ = (
        UniqueConstraint("debt_id", name="uq_debt_voids_debt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    debt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("debts.id", name="fk_debt_voids_debt"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_debt_voids_actor_account"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DebtForgiveness(Base):
    """Append-only creditor waiver of a member Debt's remaining; see ADR-0049 §3.7 / §4.

    Slice 8e-3: the creditor relinquishes their own remaining claim ("算了，不用还了")
    — a one-sided Communal gift that benefits the debtor only (no adverse interest),
    so it does NOT require debtor confirmation, unlike a member void / principal-raising
    adjustment (§3.3 / §3.5 / §5.2). The ``amount_cents`` is the ``remaining_before``
    snapshotted while serialized on the parent Debt row (§2.1), so a concurrent repayment
    and forgiveness cannot both read the same pre-state and drive ``remaining < 0``.

    ``compute_remaining`` subtracts the forgiveness total, so a forgiven Debt folds to
    ``cleared`` (a completion that counts toward §6 "two-clear"), NOT ``voided`` —
    ``derive_status`` only latches ``voided`` for an explicit ``DebtVoid``. Forgiveness is
    member-Debt + creditor only and supersedes any pending ``MemberRepaymentProposal`` in
    the same transaction. Carries ``idempotency_key`` for trace parity with the other fact
    tables; uniqueness is tenant-scoped in ``api_idempotency_keys`` (§3.6), so — like the
    slice-1 facts after 20260614_0003 — there is NO global ``UNIQUE(idempotency_key)`` here.
    """

    __tablename__ = "debt_forgivenesses"
    __table_args__ = (
        CheckConstraint(
            "amount_cents > 0", name="ck_debt_forgivenesses_amount_positive"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    debt_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("debts.id", name="fk_debt_forgivenesses_debt"),
        nullable=False,
        index=True,
    )
    # = the ``remaining_before`` snapshotted under the §2.1 parent-row lock (§3.7).
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", name="fk_debt_forgivenesses_actor_account"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_debt_forgivenesses_debt_created", DebtForgiveness.debt_id, DebtForgiveness.created_at)


class MemberRepaymentProposal(Base):
    """Debtor-side "I paid" pending intent for a member Debt; see ADR-0049 §3.2.

    A proposal is NOT an append-only fact — while ``pending`` it never enters the
    §2 fold (``remaining`` / ``paid`` ignore it). The creditor confirms it (full
    or partial) to commit one ``Repayment`` linked back via ``proposal_id``, or
    rejects it; the debtor may withdraw a still-pending proposal; creating a new
    proposal supersedes the existing pending one in the same transaction. The
    frozen ``proposed_amount_cents`` (home minor units, §2.2) plus the optional
    original-currency provenance mirror ``Repayment`` so a full confirmation can
    copy the provenance onto the committed repayment.

    ``uq_mrp_one_pending_per_debt`` (partial UNIQUE ``WHERE status = 'pending'``)
    is the §3.2 hard backstop: at most one ``pending`` proposal per Debt, so two
    concurrent creates cannot leave two pending rows for the debtor to double-fill
    and the creditor to double-confirm. The service supersede is a workflow
    convenience layered on top of — never a substitute for — this index.
    """

    __tablename__ = "member_repayment_proposals"
    __table_args__ = (
        CheckConstraint(
            "proposed_amount_cents > 0",
            name="ck_member_repayment_proposals_amount_positive",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'partially_confirmed', "
            "'rejected', 'withdrawn', 'expired', 'superseded')",
            name="ck_member_repayment_proposals_status_valid",
        ),
        CheckConstraint("length(home_currency_code) = 3", name="ck_mrp_home_currency_format"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    debt_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("debts.id", name="fk_member_repayment_proposals_debt"),
        nullable=False,
        index=True,
    )
    # --- adverse-interest parties (debtor proposes, creditor confirms) --------
    debtor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_mrp_debtor_account"), nullable=False
    )
    creditor_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_mrp_creditor_account"), nullable=False
    )
    proposed_by_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_mrp_proposed_by_account"), nullable=False
    )

    # --- money: frozen home amount + original-currency provenance (§2.2) ------
    proposed_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    home_currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    original_currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_rate_to_cny = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- lifecycle -----------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False
    )
    confirmed_amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Plain int (no FK) — mirrors Repayment.proposal_id's loose back-link style.
    committed_repayment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supersedes_proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # §3.2: a pending proposal expires after 30 days if neither side acts.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_mrp_resolved_by_account"), nullable=True
    )


Index(
    "ix_mrp_debt_status",
    MemberRepaymentProposal.debt_id,
    MemberRepaymentProposal.status,
)
# §3.2 one-pending-per-Debt backstop: a partial UNIQUE on debt_id restricted to
# pending rows so at most one proposal per Debt is ``pending`` at a time. By manual
# convention the ``postgresql_where`` predicate text is kept byte-identical to the
# migration's ``sa.text("status = 'pending'")``. Note the ``_audit_partial_index_pg_where``
# lane only flags a partial Index that declares ``sqlite_where`` WITHOUT a
# ``postgresql_where`` (which would silently degrade to a whole-table UNIQUE on
# PostgreSQL); it does NOT compare the predicate text between ORM and migration —
# that match stays a reviewer-enforced convention.
Index(
    "uq_mrp_one_pending_per_debt",
    MemberRepaymentProposal.debt_id,
    unique=True,
    postgresql_where=text("status = 'pending'"),
)
