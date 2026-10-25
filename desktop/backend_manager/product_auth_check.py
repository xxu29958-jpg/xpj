"""The existing auth/check identity, validated without retaining a credential."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_TEXT_LIMITS = {
    "server_id": 128, "data_generation": 128,
    "account_public_id": 128, "device_public_id": 128,
    "account_name": 120, "ledger_id": 64, "ledger_name": 120,
    "device_name": 120, "role": 32, "scope": 32, "credential_state": 16,
}


@dataclass(frozen=True)
class ProductAuthIdentity:
    server_id: str
    data_generation: str
    account_public_id: str
    device_public_id: str
    ledger_id: str
    role: str


def parse_auth_check(payload: Mapping[str, object] | None) -> tuple[ProductAuthIdentity, str] | None:
    """Require the closed Backend response; names are labels, never identity."""
    if payload is None or set(payload) != {"status", *_TEXT_LIMITS} or payload.get("status") != "ok":
        return None
    if any(
        not isinstance(value := payload[key], str) or not value or value != value.strip() or len(value) > limit
        for key, limit in _TEXT_LIMITS.items()
    ):
        return None
    if payload["scope"] != "app" or payload["role"] not in {"owner", "member", "viewer"}:
        return None
    state = payload["credential_state"]
    if state not in {"current", "grace"}:
        return None
    return ProductAuthIdentity(**{key: payload[key] for key in ProductAuthIdentity.__dataclass_fields__}), state
