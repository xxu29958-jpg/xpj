from __future__ import annotations

import hashlib
import hmac
import re
import secrets

_CONTEXT = b"ticketbox/installation-health/v1\0"
_MODE_CONTEXT = b"ticketbox/installation-health-mode/v1\0"
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
VALID_RUNTIME_MODES = frozenset({"normal", "upgrade_verify_only", "restore_verify_only"})


def new_challenge() -> str:
    return secrets.token_hex(32)


def sign_challenge(key: str, challenge: str) -> str:
    if _HEX_256.fullmatch(key) is None or _HEX_256.fullmatch(challenge) is None:
        raise ValueError("health attestation input is invalid")
    return hmac.new(bytes.fromhex(key), _CONTEXT + challenge.encode("ascii"), hashlib.sha256).hexdigest()


def verifies_challenge(key: str, challenge: str, candidate: object) -> bool:
    return isinstance(candidate, str) and hmac.compare_digest(
        sign_challenge(key, challenge),
        candidate,
    )


def sign_runtime_mode(key: str, challenge: str, runtime_mode: str) -> str:
    if (
        _HEX_256.fullmatch(key) is None
        or _HEX_256.fullmatch(challenge) is None
        or runtime_mode not in VALID_RUNTIME_MODES
    ):
        raise ValueError("health runtime mode attestation input is invalid")
    payload = _MODE_CONTEXT + challenge.encode("ascii") + b"\0" + runtime_mode.encode("ascii")
    return hmac.new(bytes.fromhex(key), payload, hashlib.sha256).hexdigest()


def verifies_runtime_mode(
    key: str,
    challenge: str,
    runtime_mode: str,
    candidate: object,
) -> bool:
    return isinstance(candidate, str) and hmac.compare_digest(
        sign_runtime_mode(key, challenge, runtime_mode),
        candidate,
    )
