"""Host/Origin validation, CSP, challenge signing, and bounded body readers for the control server."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from enum import Enum
from http.server import BaseHTTPRequestHandler

CONTROL_SESSION_COOKIE = "ticketbox_manager_control"
IDENTITY = {"product": "ticketbox-desktop-manager", "protocol": "v1"}
IDENTITY_RESPONSE_LIMIT = 512
CHALLENGE_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
SHA256_PROOF_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
REOPEN_REQUEST_CONTEXT = b"ticketbox-manager-reopen-request-v1\0"
REOPEN_RESPONSE_CONTEXT = b"ticketbox-manager-reopen-response-v1\0"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

_MAX_REJECTED_BODY_DRAIN_BYTES = 4096
_REJECTED_BODY_DRAIN_CHUNK_BYTES = 1024
_REJECTED_BODY_DRAIN_TIMEOUT_SECONDS = 0.25


class EmptyRequestBodyState(Enum):
    EMPTY = "empty"
    DRAINED_NONEMPTY = "drained_nonempty"
    INCOMPLETE = "incomplete"


def _normalized_host(host: str) -> str | None:
    value = host.strip().strip("[]").casefold()
    if not value:
        return None
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value if value == "localhost" else None


def authority_tuple(value: str, *, scheme: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(f"{scheme}://{value.strip()}")
        port = parsed.port
    except ValueError:
        return None
    host = _normalized_host(parsed.hostname or "")
    if (
        parsed.scheme.casefold() != scheme
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return scheme, host, port if port is not None else 80


def origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.casefold()
    host = _normalized_host(parsed.hostname or "")
    if (
        scheme != "http"
        or host is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return scheme, host, port if port is not None else 80


def host_allowed(provided_host: str | None, expected_host: str) -> bool:
    expected_authority = authority_tuple(expected_host, scheme="http")
    return (
        expected_authority is not None
        and provided_host is not None
        and authority_tuple(provided_host, scheme="http") == expected_authority
    )


def token_allowed(provided_token: str | None, expected_token: str) -> bool:
    return provided_token is not None and secrets.compare_digest(provided_token, expected_token)


def is_authorized(
    *,
    token: str,
    provided_token: str | None,
    sec_fetch_site: str | None,
    origin: str | None,
    expected_origin: str,
    provided_host: str | None,
    expected_host: str,
) -> bool:
    """Whether a mutating request may proceed (token + same-origin)."""
    if not host_allowed(provided_host, expected_host):
        return False
    if not provided_token or not secrets.compare_digest(provided_token.encode(), token.encode()):
        return False
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        return False
    expected_origin_tuple = origin_tuple(expected_origin)
    return origin is None or (expected_origin_tuple is not None and origin_tuple(origin) == expected_origin_tuple)


def sign_challenge(instance_secret: str, challenge: str, *, context: bytes = b"") -> str:
    return hmac.new(
        instance_secret.encode("utf-8"),
        context + challenge.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_loopback_manager_url(manager_url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(manager_url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        return False
    try:
        address = ipaddress.ip_address(hostname)
        loopback_v4 = address.version == 4 and address.is_loopback
    except ValueError:
        loopback_v4 = False
    return (
        parsed.scheme == "http"
        and (hostname == "localhost" or loopback_v4)
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/"
        and not parsed.query
        and not parsed.fragment
        and port is not None
    )


def _fetch_identity_payload(request: urllib.request.Request, *, timeout: float) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            media_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
            if media_type != "application/json":
                return None
            raw = response.read(IDENTITY_RESPONSE_LIMIT + 1)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if len(raw) > IDENTITY_RESPONSE_LIMIT:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != {*IDENTITY, "challenge", "proof"}:
        return None
    return payload


def _verify_identity_payload(
    payload: dict | None,
    *,
    instance_secret: str,
    challenge: str,
    context: bytes = b"",
) -> bool:
    if payload is None:
        return False
    proof = payload.get("proof")
    expected_proof = sign_challenge(instance_secret, challenge, context=context)
    return (
        payload.get("product") == IDENTITY["product"]
        and payload.get("protocol") == IDENTITY["protocol"]
        and payload.get("challenge") == challenge
        and isinstance(proof, str)
        and secrets.compare_digest(proof, expected_proof)
    )


def probe_existing_manager(manager_url: str, instance_secret: str, *, timeout: float = 0.5) -> bool:
    """Recognize an already-running local Manager before reopening its window."""
    if not _is_loopback_manager_url(manager_url):
        return False
    challenge = secrets.token_urlsafe(32)
    identity_url = urllib.parse.urljoin(manager_url, "api/identity")
    identity_url = f"{identity_url}?{urllib.parse.urlencode({'challenge': challenge})}"
    request = urllib.request.Request(identity_url, headers={"Accept": "application/json"})
    payload = _fetch_identity_payload(request, timeout=timeout)
    return _verify_identity_payload(payload, instance_secret=instance_secret, challenge=challenge)


def request_existing_manager_window(
    manager_url: str,
    instance_secret: str,
    *,
    timeout: float = 0.5,
) -> bool:
    """Ask the authenticated owner process to open and own another UI window."""
    if not probe_existing_manager(manager_url, instance_secret, timeout=timeout):
        return False
    challenge = secrets.token_urlsafe(32)
    request_proof = sign_challenge(instance_secret, challenge, context=REOPEN_REQUEST_CONTEXT)
    reopen_url = urllib.parse.urljoin(manager_url, "api/reopen")
    request = urllib.request.Request(
        reopen_url,
        data=b"",
        headers={
            "Accept": "application/json",
            "X-Ticketbox-Reopen-Challenge": challenge,
            "X-Ticketbox-Reopen-Proof": request_proof,
        },
        method="POST",
    )
    payload = _fetch_identity_payload(request, timeout=timeout)
    return _verify_identity_payload(
        payload,
        instance_secret=instance_secret,
        challenge=challenge,
        context=REOPEN_RESPONSE_CONTEXT,
    )


def _single_content_length(handler: BaseHTTPRequestHandler, *, allow_missing: bool) -> int | None:
    if handler.headers.get("Transfer-Encoding") is not None:
        return None
    lengths = handler.headers.get_all("Content-Length", [])
    if not lengths:
        return 0 if allow_missing else None
    if len(lengths) != 1:
        return None
    try:
        return int(lengths[0])
    except ValueError:
        return None


def read_bounded_body(handler: BaseHTTPRequestHandler, *, max_bytes: int) -> bytes | None:
    length = _single_content_length(handler, allow_missing=True)
    if length is None or length < 0 or length > max_bytes:
        return None
    return b"" if length == 0 else handler.rfile.read(length)


def read_json_body(handler: BaseHTTPRequestHandler, *, max_bytes: int) -> dict | None:
    length = _single_content_length(handler, allow_missing=False)
    content_type = (handler.headers.get("Content-Type") or "").partition(";")[0].strip().lower()
    if length is None or length <= 0 or length > max_bytes or content_type != "application/json":
        return None
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_empty_request_body_state(handler: BaseHTTPRequestHandler) -> EmptyRequestBodyState:
    length = _single_content_length(handler, allow_missing=True)
    if length is None:
        handler.close_connection = True
        return EmptyRequestBodyState.INCOMPLETE
    if length == 0:
        return EmptyRequestBodyState.EMPTY
    handler.close_connection = True
    if length < 0 or length > _MAX_REJECTED_BODY_DRAIN_BYTES:
        return EmptyRequestBodyState.INCOMPLETE
    deadline = time.monotonic() + _REJECTED_BODY_DRAIN_TIMEOUT_SECONDS
    remaining = length
    previous_timeout = handler.connection.gettimeout()
    try:
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                return EmptyRequestBodyState.INCOMPLETE
            handler.connection.settimeout(timeout)
            chunk = handler.rfile.read(min(remaining, _REJECTED_BODY_DRAIN_CHUNK_BYTES))
            if not chunk:
                return EmptyRequestBodyState.INCOMPLETE
            remaining -= len(chunk)
    except (OSError, TimeoutError):
        return EmptyRequestBodyState.INCOMPLETE
    finally:
        with suppress(OSError):
            handler.connection.settimeout(previous_timeout)
    return EmptyRequestBodyState.DRAINED_NONEMPTY
