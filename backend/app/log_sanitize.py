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

import copy
import logging
import re
import time
from collections.abc import Mapping
from pathlib import Path

from app.diagnostic_identity import diagnostic_build_identity

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
    """Return a redacted copy of an HTTP header mapping for logging.

    - Bearer / cookie / upload-token / bootstrap-secret / Cloudflare Access JWT /
      CSRF token fields collapse to ``***``
    - ``Referer`` / ``Origin`` values keep scheme + host but any ``/u/<key>``
      path inside them is masked (a browser-sent Referer can include the upload
      link if a user clicks an in-page link from /u/...; without this rule the
      upload_key would leak into the 5xx log via the Referer header).

    codex P2: ``cf-access-jwt-assertion`` carries the Cloudflare Access user
    identity JWT, ``x-csrf-token`` carries the per-session CSRF token. Both are
    bearer-class secrets in the same sense as ``Authorization`` and must never
    appear in 5xx error logs.
    """

    if not headers:
        return {}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in {
            "authorization",
            "upload-token",
            "x-bootstrap-secret",
            "cookie",
            "set-cookie",
            "cf-access-jwt-assertion",
            "x-csrf-token",
        }:
            redacted[key] = "***"
        elif lk in {"referer", "origin"}:
            redacted[key] = mask_upload_path(value)
        else:
            redacted[key] = value
    return redacted


_SECRET_FIELD_RE = re.compile(
    r"(?i)((?:authorization|bearer|cookie|set-cookie|upload[-_]token|upload[-_]key|"
    r"pairing[-_ ]?code|pairing|invitation|bootstrap[-_]secret|access[-_]token|refresh[-_]token|"
    r"session[-_]token|api[-_]key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'&<>]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"'<>]+")


def sanitize_log_text(value: str) -> str:
    value = _BEARER_RE.sub("Bearer ***", value)
    value = _SECRET_FIELD_RE.sub(r"\1***", mask_upload_path(value))
    value = re.sub(r"(https?://)[^\s/@]+@", r"\1***@", value)
    return _WINDOWS_PATH_RE.sub("[local-path]", value).replace("\r", r"\r")


def project_location(filename: str) -> str | None:
    normalized = filename.replace("\\", "/")
    root = Path(__file__).resolve().parents[1].as_posix() + "/"
    if normalized.startswith(root):
        return "backend/" + normalized[len(root):]
    # PyInstaller retains relative source names, or the immutable build's root.
    for prefix in ("app/", "packaging/"):
        if normalized.startswith(prefix):
            return "backend/" + normalized
        marker = "/backend/" + prefix
        if marker in normalized:
            return "backend/" + prefix + normalized.split(marker, 1)[1]
    return None


def safe_exception_text(error: BaseException) -> str:
    """Types and project frames only: no exception messages, source lines or locals."""
    lines, seen = [], set()
    while error is not None and id(error) not in seen and len(seen) < 8:
        seen.add(id(error))
        label = type(error).__name__
        code = getattr(error, "error", None)
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
            label += f" code={code}"
        lines.append(label)
        traceback = error.__traceback__
        while traceback is not None:
            frame = traceback.tb_frame
            location = project_location(frame.f_code.co_filename)
            if location:
                lines.append(f"  at {location}:{traceback.tb_lineno} in {frame.f_code.co_name}")
            traceback = traceback.tb_next
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
        if error is not None:
            lines.append("caused/context:")
    return "\n".join(lines)


class SanitizedFormatter(logging.Formatter):
    """Final file/console boundary, including Uvicorn and propagating child loggers."""

    converter = time.gmtime

    def __init__(self) -> None:
        super().__init__("%(asctime)sZ %(levelname)s [%(name)s] %(build_identity)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S")
        self.build_identity = diagnostic_build_identity()

    def format(self, record: logging.LogRecord) -> str:
        clean = copy.copy(record)
        clean.build_identity = self.build_identity
        if isinstance(clean.msg, BaseException):
            clean.msg = type(clean.msg).__name__
        if isinstance(clean.args, tuple):
            clean.args = tuple(type(value).__name__ if isinstance(value, BaseException) else value for value in clean.args)
        clean.msg = sanitize_log_text(clean.getMessage()).replace("\n", r"\n")
        clean.args = ()
        # Never reuse another formatter's raw traceback or exception message.
        clean.exc_text = safe_exception_text(clean.exc_info[1]) if clean.exc_info else None
        clean.exc_info = None
        clean.stack_info = None  # Stack-info may contain source lines; exc_info has safe frames.
        location = project_location(clean.pathname)
        if location and clean.levelno >= logging.ERROR:
            clean.msg += f" reported_at={location}:{clean.lineno}"
        return sanitize_log_text(super().format(clean))
