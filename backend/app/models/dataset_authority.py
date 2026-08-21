from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database_model_registry import Base
from app.services.time_service import now_utc


class DatasetAuthorityRecord(Base):
    """The sole logical identity and compatibility authority for one dataset."""

    __tablename__ = "dataset_authority"
    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_dataset_authority_singleton"),
        CheckConstraint("restore_epoch >= 0", name="ck_dataset_authority_restore_epoch"),
        CheckConstraint(
            "dataset_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_dataset_authority_dataset_id",
        ),
        CheckConstraint(
            "client_generation ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_dataset_authority_client_generation",
        ),
        CheckConstraint(
            "schema_revision ~ '^[0-9]{8}_[0-9]{4}$'",
            name="ck_dataset_authority_schema_revision",
        ),
        CheckConstraint(
            "semantic_revision ~ '^ticketbox-dataset-semantics-v[1-9][0-9]*$'",
            name="ck_dataset_authority_semantic_revision",
        ),
        CheckConstraint(
            "restored_from_backup_id IS NULL OR restored_from_backup_id ~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            "[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_dataset_authority_backup_id",
        ),
    )

    singleton_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    dataset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_generation: Mapped[str] = mapped_column(String(36), nullable=False)
    restore_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    schema_revision: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_min_compatible: Mapped[str] = mapped_column(String(64), nullable=False)
    semantic_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_utc,
        nullable=False,
    )
    restored_from_backup_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
