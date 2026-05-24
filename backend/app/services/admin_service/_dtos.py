"""Admin service DTOs shared between device and upload-link helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceSummary:
    public_id: str
    device_name: str
    platform: str
    account_name: str
    ledger_id: str | None
    ledger_name: str | None
    created_at: str | None
    last_seen_at: str | None
    revoked_at: str | None


@dataclass(frozen=True)
class UploadLinkSummary:
    public_id: str
    ledger_id: str
    ledger_name: str
    account_name: str
    device_name: str
    default_timezone: str | None
    masked_url_path: str
    last_used_at: str | None
    revoked_at: str | None
    created_at: str | None


@dataclass(frozen=True)
class UploadLinkSecret:
    """One-shot reveal returned by create / rotate. Never persisted."""

    public_id: str
    upload_url_path: str
    default_timezone: str | None
