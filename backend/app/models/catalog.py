from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
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
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_merchant_aliases_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    canonical_merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # ADR-0038 undo: soft-delete marker. NULL = live; non-NULL = deleted and
    # hidden from every read, recoverable via POST .../undo until cleanup
    # purges it past the retention window. The (tenant_id, alias_key) unique
    # constraint stays in force, so a soft-deleted key is reserved during its
    # undo window (recreating it returns 409 until undo or purge).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class CategoryPreference(Base):
    """Ledger-level category option preference (ADR-0052).

    Expense.category remains a historical fact string. This row only controls
    whether a custom category is offered in current option surfaces.
    """

    __tablename__ = "category_preferences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_category_preferences_tenant_key"),
        CheckConstraint("kind IN ('custom')", name="ck_category_preferences_kind_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_category_preferences_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), default="custom", server_default="custom", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_tags_id_tenant_id"),
        UniqueConstraint("tenant_id", "key", name="uq_tags_tenant_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ADR-0043: stable external addressing for the tag management surface
    # (rename / delete / merge / undo).普通 UI 不暴露 id;管理 API 走 public_id。
    public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_tags_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # ADR-0041: monotonic row_version OCC token (updated_at kept for display/sort).
    row_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    # ADR-0043 undo: soft-delete marker. NULL = live; non-NULL = deleted and
    # hidden from every read (list/stats/contract filter/_ensure_tag), recoverable
    # via the tag-mutation undo group until cleanup purges it past the retention
    # window. The (tenant_id, key) unique constraint stays in force, so a
    # soft-deleted key is reserved during its undo window — implicit re-creation
    # (_ensure_tag) revives the row instead of duplicating the key (契约 4).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class ExpenseTag(Base):
    __tablename__ = "expense_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_expense_tags_expense_tenant",
        ),
        ForeignKeyConstraint(
            ["tag_id", "tenant_id"],
            ["tags.id", "tags.tenant_id"],
            name="fk_expense_tags_tag_tenant",
        ),
        UniqueConstraint("tenant_id", "expense_id", "tag_id", name="uq_expense_tags_tenant_expense_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    expense_id: Mapped[int] = mapped_column(Integer, ForeignKey("expenses.id"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class TagMutationUndoGroup(Base):
    """ADR-0043 undo snapshot anchor for one delete/merge tag mutation.

    rename is self-inverse (rename back) and writes no snapshot. delete and
    merge soft-delete the source tag and write one group row + N item rows in
    the same forward transaction (契约 1). undo claims this group by
    ``mutation_public_id`` (soft-marking ``consumed_at`` under a rowcount=1
    guard, 契约 2 步①), then revives the soft-deleted source tag and replays
    the per-expense item snapshots. The retention window anchors on this row's
    own ``created_at`` (契约 6), not the tag's ``deleted_at`` — so a revived
    tag's snapshot still purges on its own age.
    """

    __tablename__ = "tag_mutation_undo_groups"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_tag_mutation_undo_groups_id_tenant_id"),
        CheckConstraint("op IN ('delete', 'merge')", name="ck_tag_mutation_undo_groups_op_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Undo token carrier + claim point. Clients address undo by this id; the
    # soft-deleted tag's expected ``row_version`` rides the request body.
    mutation_public_id: Mapped[str] = mapped_column(
        String(36), default=lambda: str(uuid4()), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ledgers.ledger_id", name="fk_tag_mutation_undo_groups_tenant_ledger"),
        default=DEFAULT_TENANT_ID,
        nullable=False,
        index=True,
    )
    op: Mapped[str] = mapped_column(String(16), nullable=False)
    # The soft-deleted tag undo revives (delete target / merge source A). undo
    # claims it by ``public_id`` + the request's expected ``row_version``.
    source_tag_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_tag_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # merge only: the surviving tag B that A was merged into (audit/display).
    target_tag_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_tag_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    # undo claim marker (NULL = unclaimed). Set under a rowcount=1 guard so the
    # undo claim and a concurrent purge DELETE of the same row are mutually
    # exclusive on the row lock (契约 6).
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class TagMutationUndoItem(Base):
    """ADR-0043 per-expense snapshot row under a :class:`TagMutationUndoGroup`.

    Records each expense the forward delete/merge touched, capturing the
    pre-mutation denormalised string, the exact original tag-id set, and the
    expense's pre-mutation ``row_version``. undo replays each item with a
    per-expense CAS on ``original_row_version`` (skipped — never overwritten —
    if the expense moved on, 契约 2 步③).
    """

    __tablename__ = "tag_mutation_undo_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "tenant_id"],
            ["tag_mutation_undo_groups.id", "tag_mutation_undo_groups.tenant_id"],
            name="fk_tag_mutation_undo_items_group_tenant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default=DEFAULT_TENANT_ID, nullable=False, index=True)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expense_public_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Pre-mutation ``expenses.tags`` denormalised string (NULL = had no string).
    original_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pre-mutation exact tag-id set, comma-joined ints (e.g. "12,34"). undo
    # rebuilds expense_tags to exactly this set.
    original_tag_ids: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Pre-mutation expense ``row_version`` for the undo per-expense CAS.
    original_row_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class DuplicateIgnore(Base):
    __tablename__ = "duplicate_ignores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["expense_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_duplicate_ignores_expense_tenant",
        ),
        ForeignKeyConstraint(
            ["duplicate_of_id", "tenant_id"],
            ["expenses.id", "expenses.tenant_id"],
            name="fk_duplicate_ignores_duplicate_tenant",
        ),
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
Index("ix_category_preferences_tenant_key", CategoryPreference.tenant_id, CategoryPreference.key)
Index("ix_category_preferences_tenant_name", CategoryPreference.tenant_id, CategoryPreference.name)
Index("ix_category_preferences_tenant_deleted", CategoryPreference.tenant_id, CategoryPreference.deleted_at)
Index("ix_tags_tenant_key", Tag.tenant_id, Tag.key)
Index("ix_tags_tenant_name", Tag.tenant_id, Tag.name)
Index("ix_tags_tenant_deleted", Tag.tenant_id, Tag.deleted_at)
Index("ix_expense_tags_tenant_expense", ExpenseTag.tenant_id, ExpenseTag.expense_id)
Index("ix_expense_tags_tenant_tag", ExpenseTag.tenant_id, ExpenseTag.tag_id)
Index(
    "ix_tag_mutation_undo_groups_tenant_created",
    TagMutationUndoGroup.tenant_id,
    TagMutationUndoGroup.created_at,
)
Index(
    "ix_tag_mutation_undo_items_tenant_group",
    TagMutationUndoItem.tenant_id,
    TagMutationUndoItem.group_id,
)
Index("ix_duplicate_ignores_tenant_pair_kind", DuplicateIgnore.tenant_id, DuplicateIgnore.expense_id, DuplicateIgnore.duplicate_of_id, DuplicateIgnore.kind)
