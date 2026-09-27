"""Immutable spending-goal definitions; Goal retains the current projection."""

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


class GoalRevision(Base):
    __tablename__ = "goal_revisions"
    __table_args__ = (
        ForeignKeyConstraint(["goal_id", "tenant_id"], ["goals.id", "goals.tenant_id"],
            name="fk_goal_revision_goal_tenant", ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "goal_id", "row_version", name="uq_goal_revision_version"),
        CheckConstraint("row_version >= 1", name="ck_goal_revision_version"),
        CheckConstraint("change_kind IN ('baseline', 'create', 'edit', 'archive', 'restore')", name="ck_goal_revision_kind"),
        CheckConstraint("snapshot ->> 'goal_type' = 'spending_limit'", name="ck_goal_revision_spending_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    goal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", name="fk_goal_revision_actor", ondelete="RESTRICT"), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


event.listen(GoalRevision.__table__, "after_create", DDL("""
    CREATE OR REPLACE FUNCTION ticketbox_goal_revision_immutable()
    RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'goal revisions are immutable' USING ERRCODE = '55000';
    END $$;
    CREATE TRIGGER trg_goal_revision_immutable BEFORE UPDATE OR DELETE ON goal_revisions
    FOR EACH ROW EXECUTE FUNCTION ticketbox_goal_revision_immutable();
""").execute_if(dialect="postgresql"))
