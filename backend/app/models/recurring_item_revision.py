"""Immutable accepted series definitions, independent of observations and payments."""

from datetime import datetime

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base


class RecurringItemRevision(Base):
    __tablename__ = "recurring_item_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["series_id", "tenant_id"], ["recurring_items.id", "recurring_items.tenant_id"],
            name="fk_recurring_item_revision_series_tenant", ondelete="RESTRICT"),
        UniqueConstraint("series_id", "tenant_id", "row_version", name="uq_recurring_item_revision_version"),
        CheckConstraint("row_version >= 1", name="ck_recurring_item_revision_version"),
        CheckConstraint("change_kind IN ('baseline', 'create', 'edit', 'pause', 'resume', 'archive', 'restore')",
            name="ck_recurring_item_revision_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    series_id: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_recurring_item_revision_actor", ondelete="RESTRICT"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


event.listen(RecurringItemRevision.__table__, "after_create", DDL("""
    CREATE OR REPLACE FUNCTION ticketbox_recurring_item_revision_immutable()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'recurring item revisions are immutable' USING ERRCODE = '55000';
    END $$;
    CREATE TRIGGER trg_recurring_item_revision_immutable BEFORE UPDATE OR DELETE ON recurring_item_revisions
    FOR EACH ROW EXECUTE FUNCTION ticketbox_recurring_item_revision_immutable();
""").execute_if(dialect="postgresql"))
