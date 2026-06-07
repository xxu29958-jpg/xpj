"""ADR-0043 tag-management result contracts (split from tag_management_service
for §1 file size). Shared by tag_management_service + tag_undo_service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagUsageItem:
    public_id: str
    name: str
    usage_count: int
    row_version: int


@dataclass(frozen=True)
class TagMutationResult:
    """Result of a delete/merge. ``source_tag_row_version`` is the undo token —
    the soft-deleted source tag's new ``row_version`` (契约 2 step ②)."""

    mutation_public_id: str
    op: str
    source_tag_public_id: str
    source_tag_row_version: int
    target_tag_public_id: str | None
    target_tag_row_version: int | None
    affected_expense_count: int


@dataclass(frozen=True)
class TagUndoResult:
    restored_tag_public_id: str
    restored_tag_row_version: int
    applied: int
    skipped: int
