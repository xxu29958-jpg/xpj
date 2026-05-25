"""Identity service: bootstrap / seed / pairing / token issue / auth / pair.

Split into 7 private sub-modules by responsibility:

- ``_models``: DTOs + numeric constants.
- ``_pairing_throttle``: in-process rate limit for pair attempts (module-level state).
- ``_legacy_compat``: pre-v0.3 ``app_token`` / ``upload_token`` recognizers.
- ``_seed``: owner/ledger/membership ensure + ``ledger_ids`` query.
- ``_device``: device + auth_token / upload_link / pairing_code issuance.
- ``_bootstrap``: first-time ``bootstrap_owner`` ceremony.
- ``_auth``: ``authenticate_session_token`` / ``authenticate_web_session_token`` / ``authenticate_upload_link`` + ``_role_for``.
- ``_pair``: ``pair_device`` (consume pairing_code → mint session token).

Also re-exports ``hash_secret`` / ``hash_pairing_code`` / ``new_session_token``
/ ``new_upload_key`` from ``session_lifecycle_service`` because legacy callers
import them via ``app.services.identity_service``.
"""

from __future__ import annotations

from app.services.identity_service._auth import (
    authenticate_session_token,
    authenticate_upload_link,
    authenticate_web_session_token,
    find_active_upload_link,
    upload_link_default_timezone,
)
from app.services.identity_service._bootstrap import (
    bootstrap_owner,
    is_bootstrap_secret_consumed,
    record_bootstrap_secret_consumption,
)
from app.services.identity_service._device import (
    _create_auth_token,
    _create_pairing_code,
    _ensure_device,
    create_pairing_code,
)
from app.services.identity_service._legacy_compat import (
    is_legacy_app_token,
    is_legacy_upload_token,
)
from app.services.identity_service._models import (
    DEFAULT_ACCOUNT_NAME,
    DEFAULT_BOOTSTRAP_DEVICE_NAME,
    PAIRING_ATTEMPT_WINDOW,
    PAIRING_CODE_TTL_MINUTES,
    PAIRING_MAX_FAILED_ATTEMPTS,
    WEB_SESSION_TTL_SECONDS,
    BootstrapResult,
    PairingCodeResult,
    PairingResult,
    WebSessionAuthResult,
)
from app.services.identity_service._pair import pair_device
from app.services.identity_service._seed import (
    _ensure_membership,
    _ledger_by_id,
    active_auth_token_count,
    ensure_identity_for_existing_ledger_ids,
    ensure_identity_seed,
    ledger_ids,
)
from app.services.session_lifecycle_service import (
    hash_pairing_code,
    hash_secret,
    new_pairing_code,
    new_session_token,
    new_upload_key,
)

__all__ = [
    # constants
    "DEFAULT_ACCOUNT_NAME",
    "DEFAULT_BOOTSTRAP_DEVICE_NAME",
    "PAIRING_ATTEMPT_WINDOW",
    "PAIRING_CODE_TTL_MINUTES",
    "PAIRING_MAX_FAILED_ATTEMPTS",
    "WEB_SESSION_TTL_SECONDS",
    # DTOs
    "BootstrapResult",
    "PairingCodeResult",
    "PairingResult",
    "WebSessionAuthResult",
    # public API
    "active_auth_token_count",
    "authenticate_session_token",
    "authenticate_upload_link",
    "authenticate_web_session_token",
    "find_active_upload_link",
    "bootstrap_owner",
    "create_pairing_code",
    "is_bootstrap_secret_consumed",
    "record_bootstrap_secret_consumption",
    "ensure_identity_for_existing_ledger_ids",
    "ensure_identity_seed",
    "is_legacy_app_token",
    "is_legacy_upload_token",
    "ledger_ids",
    "pair_device",
    "upload_link_default_timezone",
    # re-exported from session_lifecycle_service
    "hash_pairing_code",
    "hash_secret",
    "new_pairing_code",
    "new_session_token",
    "new_upload_key",
    # private helpers exported because callers import them by name
    "_create_auth_token",
    "_create_pairing_code",
    "_ensure_device",
    "_ensure_membership",
    "_ledger_by_id",
]
