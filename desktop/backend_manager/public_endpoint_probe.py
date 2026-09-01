"""Bounded public Ticketbox product and route-boundary probes."""

from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol

from backend_manager.product_identity import ProductSession
from backend_manager.public_connectivity import BoundaryState, PublicState

BOUNDARY_GET_PATHS: Final = (
    "/owner",
    "/desktop/session/revoke",
    "/api/health/installation",
    "/api/status/private",
    "/api/admin/devices",
    "/api/maintenance/learning-status",
    "/api/bootstrap/owner",
    "/u/ticketbox-public-probe-no-capability",
    "/uploads/ticketbox-public-probe-missing",
    "/static/uploads/ticketbox-public-probe-missing",
)
_ALLOWED_GET_PATHS: Final = frozenset(
    {
        "/api/health",
        "/api/auth/check",
        *BOUNDARY_GET_PATHS,
    }
)
_EXPLICIT_DENIALS: Final = frozenset({401, 403, 404, 405})
_AUTH_KEYS: Final = frozenset(
    {
        "status",
        "server_id",
        "data_generation",
        "account_public_id",
        "device_public_id",
        "account_name",
        "ledger_id",
        "ledger_name",
        "device_name",
        "role",
        "scope",
    }
)
_AUTH_TEXT_LIMITS: Final = {
    "server_id": 128,
    "data_generation": 128,
    "account_public_id": 128,
    "device_public_id": 128,
    "account_name": 120,
    "ledger_id": 64,
    "ledger_name": 120,
    "device_name": 120,
    "role": 32,
    "scope": 32,
}


class PublicEndpointProbeError(RuntimeError):
    """A fixed public-probe failure that never includes transport detail."""


@dataclass(frozen=True)
class PublicEndpointContext:
    public_origin: str | None
    session: ProductSession | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BoundedHttpResponse:
    status: int
    payload: dict[str, object] | None
    redirected: bool = False


@dataclass(frozen=True)
class PublicEndpointProbeResult:
    public: PublicState
    boundary: BoundaryState
    code: str


class PublicTransport(Protocol):
    def get(
        self,
        path: str,
        *,
        session_token: str | None = None,
    ) -> BoundedHttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _normalize_public_origin(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        parsed = urllib.parse.urlsplit(raw.strip())
        port = parsed.port
    except (TypeError, ValueError):
        return None
    hostname = (parsed.hostname or "").strip().casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or port == 0
        or hostname == "localhost"
        or hostname.endswith(".localhost")
    ):
        return None
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return None
    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if not ascii_host or len(ascii_host) > 253 or "." not in ascii_host:
        return None
    authority = f"{ascii_host}:{port}" if port is not None else ascii_host
    return f"https://{authority}"


def _valid_session_token(value: str) -> str:
    token = value.strip()
    if (
        not token
        or len(token) > 512
        or token != value
        or any(character.isspace() for character in token)
        or "\r" in token
        or "\n" in token
    ):
        raise PublicEndpointProbeError("invalid Desktop session")
    return token


class BoundedHttpsTransport:
    """One-origin, GET-only HTTPS transport with a total request budget."""

    def __init__(
        self,
        public_origin: str,
        *,
        timeout_seconds: float = 1.0,
        deadline_seconds: float = 8.0,
        max_requests: int = 16,
        max_response_bytes: int = 8 * 1024,
        opener: urllib.request.OpenerDirector | None = None,
        monotonic=time.monotonic,
    ) -> None:
        normalized = _normalize_public_origin(public_origin)
        if normalized is None:
            raise PublicEndpointProbeError("invalid public origin")
        if (
            timeout_seconds <= 0
            or deadline_seconds <= 0
            or max_requests <= 0
            or max_response_bytes <= 0
        ):
            raise ValueError("public probe limits must be positive")
        self._origin = normalized
        self._timeout_seconds = timeout_seconds
        self._deadline_seconds = deadline_seconds
        self._max_requests = max_requests
        self._max_response_bytes = max_response_bytes
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._request_count = 0
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )

    def get(
        self,
        path: str,
        *,
        session_token: str | None = None,
    ) -> BoundedHttpResponse:
        if path not in _ALLOWED_GET_PATHS:
            raise PublicEndpointProbeError("invalid public probe path")
        elapsed = self._monotonic() - self._started_at
        remaining = self._deadline_seconds - elapsed
        if self._request_count >= self._max_requests or remaining <= 0:
            raise PublicEndpointProbeError("public probe budget exhausted")
        self._request_count += 1
        headers = {"Accept": "application/json"}
        if session_token is not None:
            headers["Authorization"] = f"Bearer {_valid_session_token(session_token)}"
        request = urllib.request.Request(
            f"{self._origin}{path}",
            headers=headers,
            method="GET",
        )
        timeout = min(self._timeout_seconds, remaining)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status = int(response.status)
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(self._max_response_bytes + 1)
                redirected = False
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            content_type = exc.headers.get("Content-Type", "") if exc.headers is not None else ""
            raw = exc.read(self._max_response_bytes + 1)
            redirected = 300 <= status < 400
        except (OSError, TimeoutError, ValueError, urllib.error.URLError):
            raise PublicEndpointProbeError("public endpoint request failed") from None
        if len(raw) > self._max_response_bytes:
            raise PublicEndpointProbeError("public endpoint response exceeds limit")
        payload = self._decode_payload(raw, content_type)
        return BoundedHttpResponse(status=status, payload=payload, redirected=redirected)

    @staticmethod
    def _decode_payload(raw: bytes, content_type: str) -> dict[str, object] | None:
        media_type = content_type.partition(";")[0].strip().casefold()
        if media_type != "application/json":
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise PublicEndpointProbeError("public endpoint returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise PublicEndpointProbeError("public endpoint JSON schema is invalid")
        return payload


def _safe_get(
    transport: PublicTransport,
    path: str,
    *,
    session_token: str | None = None,
) -> BoundedHttpResponse | None:
    try:
        return transport.get(path, session_token=session_token)
    except (PublicEndpointProbeError, OSError, TimeoutError, ValueError):
        return None


def _boundary_result(transport: PublicTransport) -> BoundaryState:
    responses = [_safe_get(transport, "/api/auth/check")]
    responses.extend(_safe_get(transport, path) for path in BOUNDARY_GET_PATHS)
    violation = False
    ambiguous = False
    for response in responses:
        if response is None or response.redirected:
            ambiguous = True
        elif 200 <= response.status < 300:
            violation = True
        elif response.status not in _EXPLICIT_DENIALS:
            ambiguous = True
    if violation:
        return BoundaryState.VIOLATION
    return BoundaryState.UNKNOWN if ambiguous else BoundaryState.SAFE


def _required_auth_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    limit = _AUTH_TEXT_LIMITS[key]
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > limit:
        return None
    return value


def _auth_matches_session(payload: dict[str, object] | None, session: ProductSession) -> bool:
    if payload is None or set(payload) != _AUTH_KEYS or payload.get("status") != "ok":
        return False
    values = {key: _required_auth_text(payload, key) for key in _AUTH_TEXT_LIMITS}
    if any(value is None for value in values.values()) or values["scope"] != "app":
        return False
    return (
        values["account_name"] == session.account_name
        and values["ledger_id"] == session.ledger_id
        and values["ledger_name"] == session.ledger_name
        and values["device_name"] == session.device_name
        and values["role"] == session.role
    )


def _public_result(
    transport: PublicTransport,
    session: ProductSession | None,
) -> tuple[PublicState, str]:
    if session is None:
        return PublicState.REACHABLE_UNVERIFIED, "public_reachable_unverified"
    response = _safe_get(
        transport,
        "/api/auth/check",
        session_token=session.session_token,
    )
    if response is None or response.redirected or response.status != 200:
        return PublicState.REACHABLE_UNVERIFIED, "public_session_unverified"
    if not _auth_matches_session(response.payload, session):
        return PublicState.WRONG_PRODUCT, "public_endpoint_wrong_product"
    return PublicState.AUTHENTICATED_REACHABLE, "public_authenticated_reachable"


def probe_public_endpoint(
    context: PublicEndpointContext,
    *,
    transport: PublicTransport | None = None,
) -> PublicEndpointProbeResult:
    if context.public_origin is None or not context.public_origin.strip():
        return PublicEndpointProbeResult(
            public=PublicState.UNCONFIGURED,
            boundary=BoundaryState.UNKNOWN,
            code="public_endpoint_unconfigured",
        )
    normalized = _normalize_public_origin(context.public_origin)
    if normalized is None:
        return PublicEndpointProbeResult(
            public=PublicState.UNKNOWN,
            boundary=BoundaryState.UNKNOWN,
            code="public_origin_invalid",
        )
    http = transport or BoundedHttpsTransport(normalized)
    health = _safe_get(http, "/api/health")
    if health is None or health.redirected or health.status != 200:
        return PublicEndpointProbeResult(
            public=PublicState.UNREACHABLE,
            boundary=BoundaryState.UNKNOWN,
            code="public_endpoint_unreachable",
        )
    if health.payload != {"status": "ok"}:
        return PublicEndpointProbeResult(
            public=PublicState.WRONG_PRODUCT,
            boundary=BoundaryState.UNKNOWN,
            code="public_endpoint_wrong_product",
        )
    boundary = _boundary_result(http)
    public, code = _public_result(http, context.session)
    if boundary is BoundaryState.VIOLATION:
        code = "public_boundary_violation"
    return PublicEndpointProbeResult(public=public, boundary=boundary, code=code)
