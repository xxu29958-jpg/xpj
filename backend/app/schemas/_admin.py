"""Owner / admin surfaces: data quality, maintenance, server settings, prefs.

Heterogeneous bucket for owner-only and per-account configuration responses
that don't fit the identity, expense, or rules domains. ``ServerSettings`` and
``UserUiPreferences`` are kept here despite being user-facing because their
shape is dictated by the owner-console-driven runtime state, not the regular
expense workflow.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

__all__ = [
    "DataQualitySummaryResponse",
    "MaintenanceAuditCleanupResponse",
    "MaintenanceCleanupResponse",
    "MaintenanceOrphanCleanupResponse",
    "ServerSettingsResponse",
    "UserUiPreferencesResponse",
    "UserUiPreferencesUpdateRequest",
]


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


class MaintenanceAuditCleanupResponse(BaseModel):
    deleted_rows: int
    batch_size: int


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


# v0.10: User UI preferences (cross-surface theme sync, etc.)
class UserUiPreferencesResponse(BaseModel):
    theme: str | None = None
    updated_at: datetime | None = None


class UserUiPreferencesUpdateRequest(BaseModel):
    theme: str | None = None
