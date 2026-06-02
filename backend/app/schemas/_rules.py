"""Classification rules surface: category rules, merchant aliases, rule engine.

Covers CRUD for ``CategoryRule`` and ``MerchantAlias`` plus the v0.4-alpha3
preview / apply / rollback flows for the rules engine.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso

__all__ = [
    "CategoryRuleCreateRequest",
    "CategoryRuleResponse",
    "CategoryRuleUpdateRequest",
    "MerchantAliasCreateRequest",
    "MerchantAliasDeleteRequest",
    "MerchantAliasListResponse",
    "MerchantAliasResponse",
    "MerchantAliasUpdateRequest",
    "RuleApplicationBatchResponse",
    "RuleApplicationListResponse",
    "RuleApplicationRollbackResponse",
    "RuleApplyConfirmedRequest",
    "RuleApplyConfirmedResponse",
    "RuleApplyPendingPreviewItem",
    "RuleApplyPendingPreviewResponse",
    "RuleApplyPendingRequest",
    "RuleApplyPendingResponse",
    "RulePreviewItem",
    "RulePreviewRequest",
    "RulePreviewResponse",
]


class CategoryRuleCreateRequest(BaseModel):
    keyword: str
    category: str
    enabled: bool = True
    priority: int = 100
    amount_min_cents: int | None = Field(default=None, ge=0)
    amount_max_cents: int | None = Field(default=None, ge=0)
    source_contains: str | None = None
    tag_contains: str | None = None


class CategoryRuleUpdateRequest(BaseModel):
    expected_row_version: int
    keyword: str | None = None
    category: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    amount_min_cents: int | None = Field(default=None, ge=0)
    amount_max_cents: int | None = Field(default=None, ge=0)
    source_contains: str | None = None
    tag_contains: str | None = None


class CategoryRuleDeleteRequest(BaseModel):
    """DELETE body for ADR-0038 optimistic concurrency on category_rule.

    DELETE carries a request body so the client's ``expected_row_version``
    can travel via the same channel as PATCH (Pydantic-typed, FastAPI-
    parsed). No query-string fallback — open-dev contract; clients must
    send body.
    """

    expected_row_version: int


class CategoryRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    category: str
    enabled: bool
    priority: int
    amount_min_cents: int | None = None
    amount_max_cents: int | None = None
    source_contains: str | None = None
    tag_contains: str | None = None
    created_at: datetime
    updated_at: datetime
    row_version: int

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class MerchantAliasCreateRequest(BaseModel):
    canonical_merchant: str = Field(min_length=1, max_length=255)
    alias: str = Field(min_length=1, max_length=255)
    enabled: bool = True


class MerchantAliasUpdateRequest(BaseModel):
    """ADR-0038 PR-2e: ``PATCH /api/merchants/aliases/{public_id}`` body.

    ``expected_row_version`` is the optimistic-concurrency token the
    client saw when it last read the alias. The service issues an
    atomic ``UPDATE ... WHERE row_version = expected`` and returns
    409 ``state_conflict`` if the row has been mutated by another
    writer between the read and this PATCH.
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int
    canonical_merchant: str | None = Field(default=None, min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None


class MerchantAliasDeleteRequest(BaseModel):
    """ADR-0038 PR-2e: ``DELETE /api/merchants/aliases/{public_id}`` body.

    Mirrors :class:`CategoryRuleDeleteRequest`: DELETE carries a body so
    ``expected_row_version`` travels the same channel as PATCH (Pydantic-
    typed, FastAPI-parsed). No query-string fallback — clients must send
    body. 409 ``state_conflict`` on stale token; 404 if the row vanished
    between the client's read and the delete.
    """

    model_config = ConfigDict(extra="forbid")

    expected_row_version: int


class MerchantAliasResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    canonical_merchant: str
    canonical_key: str
    alias: str
    alias_key: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    row_version: int

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class MerchantAliasListResponse(BaseModel):
    items: list[MerchantAliasResponse]


# v0.4-alpha3 — Rules Engine
class RulePreviewRequest(BaseModel):
    keyword: str
    target_category: str | None = None
    match_field: str = "merchant"  # "merchant" | "raw_text" | "any"
    limit: int = 10


class RulePreviewItem(BaseModel):
    id: int
    merchant: str | None
    amount_cents: int | None
    current_category: str
    suggested_category: str | None
    reason: str


class RulePreviewResponse(BaseModel):
    matched_count: int
    items: list[RulePreviewItem]


class RuleApplyPendingResponse(BaseModel):
    pending_scanned: int
    changed_count: int
    scan_limit_reached: bool = False
    scan_limit: int = 0


class RuleApplyPendingRequest(BaseModel):
    confirm: bool = False
    preview_token: str | None = None


class RuleApplyConfirmedRequest(BaseModel):
    confirm: bool = False
    preview_token: str | None = None


class RuleApplicationBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    status: str
    pending_scanned: int
    changed_count: int
    created_at: datetime
    rolled_back_at: datetime | None = None

    @field_serializer("created_at", "rolled_back_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RuleApplicationListResponse(BaseModel):
    items: list[RuleApplicationBatchResponse]


class RuleApplicationRollbackResponse(BaseModel):
    public_id: str
    status: str
    changed: int
    skipped: int
    rolled_back_at: datetime | None = None

    @field_serializer("rolled_back_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RuleApplyPendingPreviewItem(BaseModel):
    id: int
    merchant: str | None
    current_category: str
    suggested_category: str
    rule_keyword: str
    reason: str


class RuleApplyPendingPreviewResponse(BaseModel):
    pending_scanned: int
    changed_count: int
    items: list[RuleApplyPendingPreviewItem]
    skipped_non_default_category: int
    no_match_count: int
    unchanged_count: int
    conflict_count: int = 0
    scan_limit_reached: bool = False
    scan_limit: int = 0
    preview_token: str | None = None


class RuleApplyConfirmedResponse(BaseModel):
    dry_run: bool
    confirmed_scanned: int
    changed_count: int
    items: list[RuleApplyPendingPreviewItem] = Field(default_factory=list)
    skipped_non_default_category: int = 0
    no_match_count: int = 0
    unchanged_count: int = 0
    conflict_count: int = 0
    scan_limit_reached: bool = False
    scan_limit: int = 0
    preview_token: str | None = None
