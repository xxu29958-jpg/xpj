"""Log-sanitization helpers.

These helpers are used anywhere a raw secret, upload key, session token, or
``Authorization`` header value might otherwise be written to a log. The rule:

* never log a complete ``/u/<upload_key>`` URL — log ``/u/***`` instead
* never log an ``Authorization: Bearer ...`` header — log ``***`` instead
* never log a session token, upload key, bootstrap secret, or token hash
* never log absolute filesystem paths in errors that may surface to clients

The functions are intentionally synchronous, allocation-light, and side-effect
free so they can be used inside hot paths or exception handlers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_UPLOAD_PATH_RE = re.compile(r"(/u/)([A-Za-z0-9_\-]{4,})")


def mask_upload_path(value: str | None) -> str:
    """Return ``/u/***`` for any upload path. ``None`` collapses to ``''``.

    >>> mask_upload_path("/u/abc1234567890wxyz?tz=Asia/Shanghai")
    '/u/***?tz=Asia/Shanghai'
    """

    if not value:
        return ""
    return _UPLOAD_PATH_RE.sub(r"\1***", value)


def mask_token(value: str | None) -> str:
    """Mask any token-like opaque string. Returns ``***`` for non-empty input.

    Use for session tokens, upload keys, bootstrap secrets, token hashes, and
    pairing codes. Never use for non-secret short identifiers like
    ``account_name``.
    """

    if not value:
        return ""
    return "***"


def safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return a redacted copy of an HTTP header mapping for logging."""

    if not headers:
        return {}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in {"authorization", "upload-token", "x-bootstrap-secret", "cookie", "set-cookie"}:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted
