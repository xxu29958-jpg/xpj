from __future__ import annotations

import hashlib
import hmac
import re
import secrets

_CONTEXT = b"ticketbox/installation-health/v1\0"
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")


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
