"""Identity-service DTOs + constants (leaf).

Module-level state (e.g. pairing rate-limit failures) lives in
``_pairing_throttle`` instead, so this stays pure data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.tenants import AuthContext

DEFAULT_ACCOUNT_NAME = "我"
DEFAULT_BOOTSTRAP_DEVICE_NAME = "Windows 后端"
PAIRING_CODE_TTL_MINUTES = 15
PAIRING_MAX_FAILED_ATTEMPTS = 20
PAIRING_ATTEMPT_WINDOW = timedelta(minutes=10)
WEB_SESSION_TTL_SECONDS = 8 * 60 * 60


@dataclass(frozen=True)
class BootstrapResult:
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    admin_token: str
    upload_key: str
    upload_url_path: str
    pairing_code: str
    pairing_expires_at: str


@dataclass(frozen=True)
class PairingResult:
    session_token: str
    account_name: str
    ledger_id: str
    ledger_name: str
    device_name: str
    role: str


@dataclass(frozen=True)
class PairingCodeResult:
    pairing_code: str
    ledger_name: str
    expires_at: str


@dataclass(frozen=True)
class WebSessionAuthResult:
    auth: AuthContext
    refreshed: bool
