"""Result contracts returned by ledger application services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerSummary:
    ledger_id: str
    name: str
    role: str
    is_default: bool
    created_at: str | None
    archived_at: str | None


@dataclass(frozen=True)
class SwitchLedgerResult:
    session_token: str
    expires_at: str | None
    soft_refresh_after: str | None
    ledger_id: str
    ledger_name: str
    role: str
    is_default: bool
    created_at: str | None
    archived_at: str | None
    account_name: str
    device_name: str
