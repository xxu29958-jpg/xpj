"""Append-only history for the current confirmed Expense projection."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class ExpenseRevision(Base):
    """One immutable publication or correction of an Expense fact.

    ``Expense`` remains the query-efficient current projection.  These rows keep
    the complete before/after evidence needed to explain and rebuild confirmed
    user facts without turning the expense domain into event sourcing.
    """

    __tablename__ = "expense_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_revisions_expense_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "expense_id",
            "revision_number",
            name="uq_expense_revisions_expense_number",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_expense_revisions_idempotency_key",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_expense_revisions_number_positive",
        ),
        CheckConstraint(
            "change_kind IN ('confirmed', 'correction')",
            name="ck_expense_revisions_kind_valid",
        ),
        CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500",
            name="ck_expense_revisions_reason_length",
        ),
        CheckConstraint(
            "(change_kind = 'confirmed' AND before_snapshot IS NULL) OR "
            "(change_kind = 'correction' AND before_snapshot IS NOT NULL)",
            name="ck_expense_revisions_before_shape",
        ),
        CheckConstraint(
            "resulting_row_version >= 1",
            name="ck_expense_revisions_resulting_row_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "accounts.id",
            name="fk_expense_revisions_actor_account",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    actor_device_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "devices.id",
            name="fk_expense_revisions_actor_device",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    before_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    after_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    previous_row_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resulting_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index(
    "ix_expense_revisions_tenant_expense_revision",
    ExpenseRevision.tenant_id,
    ExpenseRevision.expense_id,
    ExpenseRevision.revision_number,
)
Index(
    "ix_expense_revisions_actor_created",
    ExpenseRevision.actor_account_id,
    ExpenseRevision.created_at,
)

# ``create_all`` is the fresh-install path, so append-only enforcement cannot
# live only in Alembic.  Install the same PostgreSQL trigger on both schema paths.
event.listen(
    ExpenseRevision.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION ticketbox_reject_expense_revision_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'expense_revisions is append-only' USING ERRCODE = '55000'; "
        "END $$"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    ExpenseRevision.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_expense_revisions_append_only "
        "BEFORE UPDATE OR DELETE ON expense_revisions FOR EACH ROW "
        "EXECUTE FUNCTION ticketbox_reject_expense_revision_mutation()"
    ).execute_if(dialect="postgresql"),
)
