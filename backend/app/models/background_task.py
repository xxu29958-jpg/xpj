"""ADR-0030 long-task execution model.

`background_tasks` is the in-process progress table used by csv-import,
v1-migration, and future long-running user-triggered work. It is a
cross-cutting infrastructure table (not tied to a single business domain),
which is why it lives in its own module rather than next to expense /
identity / budget.

``tenant_id`` is nullable so system-wide tasks (e.g. v1.0 cut-over
migration) can record progress without binding to a single ledger. User-
scoped tasks (csv import) MUST set ``tenant_id`` so the user can only see
their own ledger's task list.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class BackgroundTask(Base):
    """Single row per user-triggered long task; queried via
    ``GET /api/tasks/{public_id}`` and ``GET /api/tasks``.

    State machine (status column):

    ``queued`` -> ``running`` -> ``completed`` | ``failed`` | ``cancelled``

    Orphan recovery: on startup, active rows are force-failed by default
    because the in-process executor that owned them died with the old process.
    Cloud / multi-worker deployments can configure a grace window for fresh
    heartbeating rows; every runner still has to atomically claim ``queued``.
    """

    __tablename__ = "background_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_background_tasks_status_valid",
        ),
        CheckConstraint(
            "progress_current >= 0",
            name="ck_background_tasks_progress_current_non_negative",
        ),
        CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name="ck_background_tasks_progress_total_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    # NULL = system-wide task (e.g. v1.0 migration); set = ledger-scoped task.
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    initiated_by_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    initiated_by_device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued", nullable=False, index=True
    )
    progress_current: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded; per-task shape (e.g. csv_import returns rows_imported / errors).
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_progress_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# Composite indexes — match the two main query patterns
Index(
    "ix_background_tasks_account_created",
    BackgroundTask.initiated_by_account_id,
    BackgroundTask.created_at,
)
Index(
    "ix_background_tasks_status_last_progress",
    BackgroundTask.status,
    BackgroundTask.last_progress_at,
)
