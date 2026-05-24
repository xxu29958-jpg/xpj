"""ADR-0031 ``app_meta`` key-value table — schema version + cut-over state.

Single-key API by design (``get(key) / set(key, value)``). Keys:

- ``schema_version`` (free-form string, e.g. ``"0.9"`` or ``"1.0"``) —
  what the DB believes its schema is.
- ``schema_min_compatible`` (free-form string) — the lowest backend
  version that this DB can still be opened by. After a v1.0 cut-over
  it gets set to ``"1.0"``; old v0.9 binaries seeing this value at
  startup must refuse to mount.
- ``migration_completed_at`` (ISO-8601 UTC) — set when cut-over finishes.
- ``identity_schema_version`` — mirror of [[ADR-0028]] frozen v0.3
  ``IDENTITY_SCHEMA_VERSION`` constant. Lives here so future cut-overs
  can sanity-check identity stability without depending on a Python
  constant.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc


class AppMeta(Base):
    """Single row per ``key``."""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


# Public key constants. Tests / handlers use these instead of literals.
SCHEMA_VERSION_KEY = "schema_version"
SCHEMA_MIN_COMPATIBLE_KEY = "schema_min_compatible"
MIGRATION_COMPLETED_AT_KEY = "migration_completed_at"
IDENTITY_SCHEMA_VERSION_KEY = "identity_schema_version"
# v1.2 ops: when the maintenance route last ran the learning-table
# retention cleanup. Owner Console shows it; cleanup-scheduling logic
# (future scheduled-task lane) reads it to decide whether to skip.
LEARNING_CLEANUP_LAST_RUN_KEY = "learning_cleanup_last_run_at"
