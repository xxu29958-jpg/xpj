from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.services.time_service import to_iso


class ErrorResponse(BaseModel):
    error: str
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    backend_version: str | None = None
    identity_schema: str | None = None
    database_status: str | None = None
    upload_dir_status: str | None = None
    owner_console_status: str | None = None


class AuthCheckResponse(BaseModel):
    status: str = "ok"
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str
    scope: str


class PairRequest(BaseModel):
    pairing_code: str = Field(min_length=1, max_length=32)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=32)


class PairResponse(BaseModel):
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


class LedgerResponse(BaseModel):
    ledger_id: str
    name: str
    role: str
    is_default: bool
    created_at: str | None = None
    archived_at: str | None = None


class LedgerListResponse(BaseModel):
    ledgers: list[LedgerResponse]


class LedgerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class LedgerSwitchResponse(BaseModel):
    session_token: str
    ledger: LedgerResponse
    account_name: str
    device_name: str


# v0.4-beta1 — family ledger invitations & members
class InvitationCreateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=80)
    ttl_days: int = Field(default=7, ge=1, le=30)


class InvitationSummaryResponse(BaseModel):
    public_id: str
    ledger_id: str
    role: str
    note: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    used_at: str | None = None
    revoked_at: str | None = None
    used_by_account_name: str | None = None


class InvitationCreateResponse(BaseModel):
    invite_token: str
    invitation: InvitationSummaryResponse


class InvitationListResponse(BaseModel):
    invitations: list[InvitationSummaryResponse]


class InvitationAcceptRequest(BaseModel):
    invite_token: str = Field(min_length=1, max_length=128)
    account_name: str = Field(min_length=1, max_length=120)
    device_name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=32)


class InvitationPreviewRequest(BaseModel):
    invite_token: str = Field(min_length=1, max_length=128)


class InvitationPreviewResponse(BaseModel):
    ledger_id: str
    ledger_name: str
    role: str
    expires_at: str | None = None


class InvitationAcceptResponse(BaseModel):
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


class LedgerMemberResponse(BaseModel):
    member_id: int
    account_public_id: str
    account_name: str
    role: str
    created_at: str | None = None
    disabled_at: str | None = None
    is_self: bool


class LedgerMemberListResponse(BaseModel):
    members: list[LedgerMemberResponse]


class LedgerMemberRoleUpdateRequest(BaseModel):
    role: str = Field(min_length=1, max_length=32)


class LedgerAuditResponse(BaseModel):
    public_id: str
    ledger_id: str
    action: str
    actor_account_public_id: str | None = None
    actor_account_name: str | None = None
    target_account_public_id: str | None = None
    target_account_name: str | None = None
    target_member_id: int | None = None
    invitation_public_id: str | None = None
    previous_role: str | None = None
    new_role: str | None = None
    result: str
    detail: str | None = None
    created_at: str | None = None


class LedgerAuditListResponse(BaseModel):
    items: list[LedgerAuditResponse]


class OwnerTransferResponse(BaseModel):
    ledger_id: str
    previous_owner: LedgerMemberResponse
    new_owner: LedgerMemberResponse


class BootstrapOwnerRequest(BaseModel):
    account_name: str | None = None
    ledger_name: str | None = None
    device_name: str | None = None
    default_timezone: str | None = None


class BootstrapOwnerResponse(BaseModel):
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    admin_token: str
    upload_key: str
    upload_url_path: str
    pairing_code: str
    pairing_expires_at: str


class PairingCodeCreateRequest(BaseModel):
    device_name_hint: str | None = None
    ttl_minutes: int = Field(default=15, ge=1, le=60)


class PairingCodeResponse(BaseModel):
    pairing_code: str
    ledger_name: str
    expires_at: str


# v0.3.1-alpha2 Phase 3 / 4 — admin device & UploadLink management.
class AdminDeviceResponse(BaseModel):
    public_id: str
    device_name: str
    platform: str
    account_name: str
    ledger_id: str | None = None
    ledger_name: str | None = None
    last_seen_at: str | None = None
    revoked_at: str | None = None


class AdminDeviceRenameRequest(BaseModel):
    device_name: str = Field(min_length=1, max_length=120)


class AdminUploadLinkResponse(BaseModel):
    public_id: str
    ledger_id: str
    ledger_name: str
    account_name: str
    device_name: str
    default_timezone: str | None = None
    masked_url_path: str
    last_used_at: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None


class AdminUploadLinkCreateRequest(BaseModel):
    ledger_id: str | None = None
    default_timezone: str | None = None


class AdminUploadLinkSecretResponse(BaseModel):
    """One-shot reveal returned by create / rotate. The full upload URL is
    only present in this response and never re-served."""

    link: AdminUploadLinkResponse
    upload_url_path: str
    default_timezone: str | None = None


class StatusResponse(BaseModel):
    status: str = "ok"


class UploadResponse(BaseModel):
    id: int
    public_id: str
    status: str
    message: str
    image_hash: str
    thumbnail_path: str | None
    duplicate_status: str
    duplicate_of_id: int | None
    upload_size_bytes: int
    duration_ms: int
    timing_ms: dict[str, int] = Field(default_factory=dict)


class UploadCheckResponse(BaseModel):
    status: str = "ok"
    max_upload_size_mb: int
    supported_file_types: list[str]
    recommended_body: str = "file"


class ExpenseManualCreateRequest(BaseModel):
    amount_cents: int | None = Field(default=None, ge=0)
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    expense_time: datetime | None = None
    tags: str | None = None
    value_score: int | None = Field(default=None, ge=1, le=5)
    regret_score: int | None = Field(default=None, ge=1, le=5)


class NotificationDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    amount_cents: int | None = Field(default=None, ge=0)
    merchant: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    expense_time: datetime | None = None


class ExpenseUpdateRequest(BaseModel):
    amount_cents: int | None = Field(default=None, ge=0)
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    expense_time: datetime | None = None
    tags: str | None = None
    value_score: int | None = Field(default=None, ge=1, le=5)
    regret_score: int | None = Field(default=None, ge=1, le=5)


class ExpenseRecognizeTextRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=20000)


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    amount_cents: int | None
    merchant: str | None
    category: str
    note: str | None
    source: str
    image_path: str | None
    thumbnail_path: str | None
    image_hash: str | None
    raw_text: str | None
    confidence: float | None
    duplicate_status: str
    duplicate_of_id: int | None
    duplicate_reason: str | None
    tags: str | None
    value_score: int | None
    regret_score: int | None
    status: str
    expense_time: datetime | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    rejected_at: datetime | None
    image_deleted_at: datetime | None
    thumbnail_deleted_at: datetime | None

    @field_serializer(
        "expense_time",
        "created_at",
        "updated_at",
        "confirmed_at",
        "rejected_at",
        "image_deleted_at",
        "thumbnail_deleted_at",
    )
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class PaginatedExpensesResponse(BaseModel):
    items: list[ExpenseResponse]
    page: int
    page_size: int
    total: int


class CategoryStatsResponse(BaseModel):
    category: str
    amount_cents: int
    count: int


class CategoriesResponse(BaseModel):
    items: list[str]


class MonthsResponse(BaseModel):
    items: list[str]


class MonthlyStatsResponse(BaseModel):
    month: str
    total_amount_cents: int
    count: int
    by_category: list[CategoryStatsResponse]


class OcrRetryResponse(BaseModel):
    id: int
    status: str
    message: str


class CategoryRuleCreateRequest(BaseModel):
    keyword: str
    category: str
    enabled: bool = True
    priority: int = 100


class CategoryRuleUpdateRequest(BaseModel):
    keyword: str | None = None
    category: str | None = None
    enabled: bool | None = None
    priority: int | None = None


class CategoryRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    category: str
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class MerchantAliasCreateRequest(BaseModel):
    canonical_merchant: str = Field(min_length=1, max_length=255)
    alias: str = Field(min_length=1, max_length=255)
    enabled: bool = True


class MerchantAliasUpdateRequest(BaseModel):
    canonical_merchant: str | None = Field(default=None, min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None


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

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class MerchantAliasListResponse(BaseModel):
    items: list[MerchantAliasResponse]


class LifestyleStatsResponse(BaseModel):
    month: str
    ai_subscription_amount_cents: int
    digital_amount_cents: int
    max_expense: ExpenseResponse | None
    recent_7_days_amount_cents: int
    frequent_merchants: list[dict[str, int | str]]


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


# v0.4-alpha3 — Recurring candidates (read-only insights)
class RecurringCandidateItem(BaseModel):
    merchant: str
    amount_cents: int
    occurrence_count: int
    last_seen_at: datetime | None
    confidence: str
    reason: str

    @field_serializer("last_seen_at")
    def serialize_last_seen_at(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecurringCandidatesResponse(BaseModel):
    items: list[RecurringCandidateItem]


# v0.6 — Formal recurring items
class RecurringCandidateConfirmRequest(BaseModel):
    merchant: str = Field(min_length=1, max_length=255)
    amount_cents: int = Field(ge=1)
    occurrence_count: int = Field(default=0, ge=0)
    last_seen_at: datetime | None = None
    confidence: str | None = Field(default=None, max_length=32)
    frequency: str = Field(default="monthly", max_length=32)
    next_expected_date: date | None = None


class RecurringItemResponse(BaseModel):
    public_id: str
    ledger_id: str
    merchant: str
    merchant_key: str
    frequency: str
    baseline_amount_cents: int
    last_amount_cents: int
    occurrence_count: int
    last_seen_at: datetime | None = None
    next_expected_date: date | None = None
    status: str
    confidence: str | None = None
    source: str
    anomaly_status: str = "none"
    current_month_amount_cents: int | None = None
    historical_average_amount_cents: int | None = None
    amount_delta_percent: int | None = None
    created_at: datetime
    updated_at: datetime
    paused_at: datetime | None = None
    archived_at: datetime | None = None

    @field_serializer("last_seen_at", "created_at", "updated_at", "paused_at", "archived_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        return to_iso(value)


class RecurringItemListResponse(BaseModel):
    items: list[RecurringItemResponse]


# v0.4-alpha3 slice 2 — Data Quality summary
class DataQualitySummaryResponse(BaseModel):
    pending_total: int
    missing_amount: int
    missing_merchant: int
    missing_category: int
    suspected_duplicates: int
    confirmed_without_image: int
    ready_to_confirm: int
    oldest_pending_age_days: int | None
    generated_at: str


class MaintenanceCleanupResponse(BaseModel):
    enabled: bool
    delete_after_days: int
    scanned: int
    deleted_images: int
    deleted_thumbnails: int


class MaintenanceOrphanCleanupResponse(BaseModel):
    dry_run: bool
    grace_hours: int
    scanned_files: int
    orphan_files: int
    deleted_files: int
    orphan_bytes: int
    deleted_bytes: int


class ServerSettingsResponse(BaseModel):
    account_name: str
    ledger_id: str
    ledger_name: str
    ledger_is_default: bool
    device_name: str
    role: str
    status: str
    storage_status: str
    pending_count: int
    confirmed_count: int
    rejected_count: int
    suspected_duplicate_count: int
    upload_storage_bytes: int
    latest_upload_at: str | None
