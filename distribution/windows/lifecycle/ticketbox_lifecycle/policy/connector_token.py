"""Validate a native-input Tunnel token without retaining it in a public record."""

from __future__ import annotations

import base64
import binascii
import json
import re
from uuid import UUID

from ticketbox_lifecycle.errors import LifecycleError


def tunnel_identity(token: str) -> str:
    try:
        if not isinstance(token, str) or not 40 <= len(token) <= 16384 or token != token.strip():
            raise ValueError
        raw = base64.b64decode(token, validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) not in ({"a", "s", "t"}, {"a", "s", "t", "e"}):
            raise ValueError
        # The pinned official struct has an optional custom Edge endpoint.
        # This fixed public-Cloudflare profile never permits that override.
        if value.get("e", "") != "":
            raise ValueError
        if not isinstance(value["a"], str) or re.fullmatch(r"[0-9a-f]{32}", value["a"]) is None:
            raise ValueError
        if not isinstance(value["s"], str) or len(base64.b64decode(value["s"], validate=True)) != 32:
            raise ValueError
        if not isinstance(value["t"], str) or str(UUID(value["t"])) != value["t"]:
            raise ValueError
        return value["t"]
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        raise LifecycleError("connector_token_invalid", "enter the dedicated Tunnel token in the native protected dialog") from None
