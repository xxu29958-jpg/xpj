from __future__ import annotations

import secrets
from uuid import uuid4


def pairing_payload(
    pairing_code: str,
    *,
    device_name: str = "pytest-android",
    platform: str = "android",
    attempt_id: str | None = None,
    attempt_secret: str | None = None,
) -> dict[str, str]:
    """Build one client-owned, retryable pairing transaction."""

    return {
        "pairing_code": pairing_code,
        "pairing_attempt_id": attempt_id or str(uuid4()),
        "pairing_attempt_secret": attempt_secret or secrets.token_urlsafe(32),
        "device_name": device_name,
        "platform": platform,
    }


def invitation_accept_payload(
    invite_token: str,
    *,
    account_name: str = "pytest-member",
    device_name: str = "pytest-android",
    platform: str = "android",
    attempt_id: str | None = None,
    attempt_secret: str | None = None,
) -> dict[str, str]:
    """Build one client-owned, retryable first-device invitation claim."""

    return {
        "invite_token": invite_token,
        "account_name": account_name,
        "device_name": device_name,
        "platform": platform,
        "enrollment_attempt_id": attempt_id or str(uuid4()),
        "enrollment_attempt_secret": attempt_secret or secrets.token_urlsafe(32),
    }


def session_refresh_payload(
    *,
    attempt_id: str | None = None,
    attempt_secret: str | None = None,
) -> dict[str, str]:
    """Build one client-owned, retryable session refresh transaction."""

    return {
        "refresh_attempt_id": attempt_id or str(uuid4()),
        "refresh_attempt_secret": attempt_secret or secrets.token_urlsafe(32),
    }
