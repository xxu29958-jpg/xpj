"""Small runtime metadata that is not dataset identity or compatibility.

Dataset lineage, restore epoch, schema compatibility, and semantic revision
belong exclusively to ``dataset_authority``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class AppMeta(Base):
    """Single row per ``key``."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


IDENTITY_SCHEMA_VERSION_KEY = "identity_schema_version"
# v1.2 ops: when the maintenance route last ran the learning-table
# retention cleanup. Owner Console shows it; cleanup-scheduling logic
# (future scheduled-task lane) reads it to decide whether to skip.
LEARNING_CLEANUP_LAST_RUN_KEY = "learning_cleanup_last_run_at"
# Free-form JSON summary of the most recent cleanup run (elapsed_ms,
# swept_stale_active, per-table deleted counts). Stored as a single
# value rather than a dedicated audit table because operators only
# need the last-run figure — long history goes in logs, not the DB.
LEARNING_CLEANUP_LAST_SUMMARY_KEY = "learning_cleanup_last_summary"
