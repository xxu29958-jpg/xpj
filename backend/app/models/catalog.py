from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.services.time_service import now_utc
from app.tenants import DEFAULT_TENANT_ID


class MerchantAlias(Base):
    __tablename__ = "merchant_aliases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "alias_key", name="uq_merchant_aliases_tenant_alias_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    canonical_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tags_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class ExpenseTag(Base):
    __tablename__ = "expense_tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_id", "tag_id", name="uq_expense_tags_tenant_expense_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DuplicateIgnore(Base):
    __tablename__ = "duplicate_ignores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_id", "duplicate_of_id", "kind", name="uq_duplicate_ignore_tenant_pair_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    duplicate_of_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


Index("ix_merchant_aliases_tenant_canonical", MerchantAlias.tenant_id, MerchantAlias.canonical_key)
Index("ix_merchant_aliases_tenant_alias_key", MerchantAlias.tenant_id, MerchantAlias.alias_key)
Index("ix_tags_tenant_key", Tag.tenant_id, Tag.key)
Index("ix_tags_tenant_name", Tag.tenant_id, Tag.name)
Index("ix_expense_tags_tenant_expense", ExpenseTag.tenant_id, ExpenseTag.expense_id)
Index("ix_expense_tags_tenant_tag", ExpenseTag.tenant_id, ExpenseTag.tag_id)
Index("ix_duplicate_ignores_tenant_pair_kind", DuplicateIgnore.tenant_id, DuplicateIgnore.expense_id, DuplicateIgnore.duplicate_of_id, DuplicateIgnore.kind)
