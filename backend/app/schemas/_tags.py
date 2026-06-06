"""ADR-0043 tag management surface: list+usage, rename, delete, merge, undo.

Distinct from ``_stats`` ``TagsResponse`` / ``TagStatsResponse`` (the read-only
tag name list + per-tag totals). These are the online-only mutate DTOs: every
mutation carries ``expected_row_version`` (OCC) and NONE declare an
``Idempotency-Key`` header (契约 7 — declaring it would make it required +
trigger the idempotency replay path).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "TagDeleteRequest",
    "TagDetailResponse",
    "TagListItem",
    "TagManagementListResponse",
    "TagMergeRequest",
    "TagMutationResponse",
    "TagRenameRequest",
    "TagUndoRequest",
    "TagUndoResponse",
]


class TagListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    name: str
    usage_count: int
    row_version: int


class TagManagementListResponse(BaseModel):
    items: list[TagListItem]


class TagRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int
    name: str = Field(min_length=1, max_length=64)


class TagDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


class TagMergeRequest(BaseModel):
    """Merge source A (the ``{public_id}`` path tag) into target B. Both tokens
    are checked; the undo token is A's (A is the soft-deleted one, 契约 2/3)."""

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int  # source A's OCC token
    target_public_id: str
    target_row_version: int  # target B's OCC token


class TagUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The soft-deleted source tag's row_version (returned by the delete/merge
    # response). Stale / already-live / purged → 409 state_conflict (契约 2 step ②).
    expected_row_version: int


class TagDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    name: str
    row_version: int


class TagMutationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mutation_public_id: str
    op: str
    source_tag_public_id: str
    source_tag_row_version: int
    target_tag_public_id: str | None = None
    target_tag_row_version: int | None = None
    affected_expense_count: int


class TagUndoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    restored_tag_public_id: str
    restored_tag_row_version: int
    applied: int
    skipped: int
