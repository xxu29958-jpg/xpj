from __future__ import annotations

import hashlib
import hmac
import re

_CONTEXT = b"ticketbox/installation-health/v1\0"
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")


def sign_health_challenge(key: str, challenge: str) -> str:
    if _HEX_256.fullmatch(key) is None or _HEX_256.fullmatch(challenge) is None:
        raise ValueError("health attestation input is invalid")
    return hmac.new(bytes.fromhex(key), _CONTEXT + challenge.encode("ascii"), hashlib.sha256).hexdigest()
