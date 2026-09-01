from __future__ import annotations

import io
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from backend_manager.product_identity import ProductSession
from backend_manager.public_connectivity import BoundaryState, PublicState
from backend_manager.public_endpoint_probe import (
    BOUNDARY_GET_PATHS,
    BoundedHttpResponse,
    BoundedHttpsTransport,
    PublicEndpointContext,
    PublicEndpointProbeError,
    probe_public_endpoint,
)

_TOKEN = "tbx_DO-NOT-EXPORT-PUBLIC-PROBE-TOKEN"


def _session(**changes: object) -> ProductSession:
    baseline = ProductSession(
        session_token=_TOKEN,
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at="2026-10-01T00:00:00Z",
    )
    return replace(baseline, **changes)


def _auth_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "server_id": "server-1",
        "data_generation": "generation-1",
        "account_public_id": "account-1",
        "device_public_id": "device-1",
        "account_name": "我",
        "ledger_id": "owner",
        "ledger_name": "我的小票夹",
        "device_name": "小票夹 Desktop",
        "role": "owner",
        "scope": "app",
        "credential_state": "current",
    }
    payload.update(changes)
    return payload


class _Transport:
    def __init__(self, responses: dict[tuple[str, bool], BoundedHttpResponse | Exception]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, bool]] = []

    def get(self, path: str, *, session_token: str | None = None) -> BoundedHttpResponse:
        key = (path, session_token is not None)
        self.requests.append(key)
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response


def _responses(
    *,
    health: BoundedHttpResponse | Exception | None = None,
    anonymous_auth: BoundedHttpResponse | Exception | None = None,
    authenticated_auth: BoundedHttpResponse | Exception | None = None,
    forbidden_status: int = 403,
) -> dict[tuple[str, bool], BoundedHttpResponse | Exception]:
    values: dict[tuple[str, bool], BoundedHttpResponse | Exception] = {
        ("/api/health", False): health or BoundedHttpResponse(200, {"status": "ok"}),
        ("/api/auth/check", False): anonymous_auth or BoundedHttpResponse(401, {"error": "invalid_token"}),
    }
    if authenticated_auth is not None:
        values[("/api/auth/check", True)] = authenticated_auth
    for path in BOUNDARY_GET_PATHS:
        values[(path, False)] = BoundedHttpResponse(forbidden_status, None)
    return values


def test_missing_public_origin_is_unconfigured_without_network_access() -> None:
    transport = _Transport({})

    result = probe_public_endpoint(PublicEndpointContext(public_origin=None), transport=transport)

    assert result.public is PublicState.UNCONFIGURED
    assert result.boundary is BoundaryState.UNKNOWN
    assert result.code == "public_endpoint_unconfigured"
    assert transport.requests == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.example",
        "https://user@public.example",
        "https://public.example/path",
        "https://public.example?query=1",
        "https://public.example#fragment",
        "https://127.0.0.1:8443",
        "https://localhost",
        "https://public.example:0",
    ],
)
def test_invalid_or_non_public_origin_fails_closed_without_network(origin: str) -> None:
    transport = _Transport({})

    result = probe_public_endpoint(PublicEndpointContext(public_origin=origin), transport=transport)

    assert result.public is PublicState.UNKNOWN
    assert result.boundary is BoundaryState.UNKNOWN
    assert result.code == "public_origin_invalid"
    assert transport.requests == []


@pytest.mark.parametrize(
    "origin",
    [
        "https://192.168.1.10:8443",
        "https://[2001:db8::1]:8443",
    ],
)
def test_backend_attested_non_loopback_ip_origin_is_probeable(origin: str) -> None:
    transport = _Transport(_responses())

    result = probe_public_endpoint(PublicEndpointContext(public_origin=origin), transport=transport)

    assert result.public is PublicState.REACHABLE_UNVERIFIED
    assert result.boundary is BoundaryState.SAFE
    assert transport.requests


def test_anonymous_health_proves_only_reachable_unverified() -> None:
    transport = _Transport(_responses())

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=transport,
    )

    assert result.public is PublicState.REACHABLE_UNVERIFIED
    assert result.boundary is BoundaryState.SAFE
    assert result.code == "public_reachable_unverified"
    assert ("/api/auth/check", True) not in transport.requests


def test_matching_desktop_session_proves_authenticated_ticketbox_product() -> None:
    transport = _Transport(_responses(authenticated_auth=BoundedHttpResponse(200, _auth_payload())))

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=transport,
    )

    assert result.public is PublicState.AUTHENTICATED_REACHABLE
    assert result.boundary is BoundaryState.SAFE
    assert result.code == "public_authenticated_reachable"
    assert transport.requests.count(("/api/auth/check", True)) == 1


def test_grace_session_is_reachable_but_never_promoted_to_authenticated() -> None:
    transport = _Transport(
        _responses(
            authenticated_auth=BoundedHttpResponse(
                200,
                _auth_payload(credential_state="grace"),
            )
        )
    )

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=transport,
    )

    assert result.public is PublicState.REACHABLE_UNVERIFIED
    assert result.boundary is BoundaryState.SAFE
    assert result.code == "public_session_unverified"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_rejected_desktop_session_keeps_valid_health_reachable_unverified(status: int) -> None:
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=_Transport(_responses(authenticated_auth=BoundedHttpResponse(status, {"error": "invalid_token"}))),
    )

    assert result.public is PublicState.REACHABLE_UNVERIFIED
    assert result.code == "public_session_unverified"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "ok"},
        _auth_payload(scope="admin"),
        _auth_payload(account_name="别人"),
        _auth_payload(ledger_id="family"),
        _auth_payload(device_name="Unknown Desktop"),
        _auth_payload(role="viewer"),
        _auth_payload(server_id=""),
        {**_auth_payload(), "unexpected": "field"},
    ],
)
def test_successful_auth_with_wrong_schema_or_local_metadata_is_wrong_product(
    payload: dict[str, object],
) -> None:
    marker = "DO-NOT-EXPORT-AUTH-MISMATCH"
    payload["ignored_marker"] = marker if "unexpected" in payload else payload.get("ignored_marker")
    if payload.get("ignored_marker") is None:
        payload.pop("ignored_marker", None)
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=_Transport(_responses(authenticated_auth=BoundedHttpResponse(200, payload))),
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.code == "public_endpoint_wrong_product"
    assert marker not in repr(result)


def test_successful_non_200_auth_with_malformed_payload_is_wrong_product() -> None:
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=_Transport(_responses(authenticated_auth=BoundedHttpResponse(201, None))),
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.code == "public_endpoint_wrong_product"


def test_non_200_auth_with_matching_schema_cannot_attest_product() -> None:
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=_session()),
        transport=_Transport(
            _responses(authenticated_auth=BoundedHttpResponse(201, _auth_payload()))
        ),
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.code == "public_endpoint_wrong_product"


@pytest.mark.parametrize(
    "health",
    [
        PublicEndpointProbeError("network unavailable"),
        BoundedHttpResponse(503, {"status": "down"}),
    ],
)
def test_health_transport_or_status_failure_is_unreachable_with_safe_denials(
    health: BoundedHttpResponse | Exception,
) -> None:
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(_responses(health=health)),
    )

    assert result.public is PublicState.UNREACHABLE
    assert result.boundary is BoundaryState.SAFE
    assert result.code == "public_endpoint_unreachable"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "healthy"},
        {"status": "ok", "installation_id": "must-not-be-public"},
        {},
    ],
)
def test_health_200_with_non_exact_contract_is_wrong_product_and_boundary_safe(
    payload: dict[str, object],
) -> None:
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(_responses(health=BoundedHttpResponse(200, payload))),
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.boundary is BoundaryState.SAFE


def test_malformed_health_still_exposes_a_forbidden_path_violation() -> None:
    responses = _responses(health=BoundedHttpResponse(200, None))
    responses[("/owner", False)] = BoundedHttpResponse(200, None)
    transport = _Transport(responses)

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=transport,
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.boundary is BoundaryState.VIOLATION
    assert result.code == "public_boundary_violation"
    assert ("/owner", False) in transport.requests


def test_unhealthy_response_still_exposes_a_forbidden_path_violation() -> None:
    responses = _responses(health=BoundedHttpResponse(503, {"status": "down"}))
    responses[("/owner", False)] = BoundedHttpResponse(200, None)

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(responses),
    )

    assert result.public is PublicState.UNREACHABLE
    assert result.boundary is BoundaryState.VIOLATION
    assert result.code == "public_boundary_violation"


def test_any_successful_forbidden_path_is_a_boundary_violation() -> None:
    responses = _responses()
    responses[("/owner", False)] = BoundedHttpResponse(200, None)

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(responses),
    )

    assert result.boundary is BoundaryState.VIOLATION
    assert result.code == "public_boundary_violation"


@pytest.mark.parametrize("denied", [401, 403, 404, 405])
def test_explicit_denials_across_all_fixed_paths_are_boundary_safe(denied: int) -> None:
    responses = _responses(forbidden_status=denied)
    responses[("/api/auth/check", False)] = BoundedHttpResponse(denied, None)

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(responses),
    )

    assert result.boundary is BoundaryState.SAFE


@pytest.mark.parametrize(
    "ambiguous",
    [
        BoundedHttpResponse(302, None, redirected=True),
        PublicEndpointProbeError("bounded timeout"),
        BoundedHttpResponse(500, None),
    ],
)
def test_redirect_timeout_or_server_error_keeps_boundary_unknown(
    ambiguous: BoundedHttpResponse | Exception,
) -> None:
    responses = _responses()
    responses[("/api/maintenance/learning-status", False)] = ambiguous

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=_Transport(responses),
    )

    assert result.boundary is BoundaryState.UNKNOWN


def test_boundary_probe_uses_only_fixed_get_paths_and_no_real_upload_capability() -> None:
    transport = _Transport(_responses())

    probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example", session=None),
        transport=transport,
    )

    paths = [path for path, _has_session in transport.requests]
    assert set(paths) == {"/api/health", "/api/auth/check", *BOUNDARY_GET_PATHS}
    assert len(paths) <= 16
    assert all("?" not in path and "#" not in path for path in paths)
    assert all(_TOKEN not in path for path in paths)
    assert "/u/ticketbox-public-probe-no-capability" in paths
    assert not any(path.startswith("/u/tbx_") for path in paths)


def test_result_and_error_never_expose_session_or_public_origin() -> None:
    marker = "DO-NOT-EXPORT-PUBLIC-ORIGIN"
    origin = f"https://{marker.lower()}.example"
    result = probe_public_endpoint(
        PublicEndpointContext(public_origin=origin, session=_session()),
        transport=_Transport(_responses(authenticated_auth=PublicEndpointProbeError("DO-NOT-EXPORT-TRANSPORT-DETAIL"))),
    )

    serialized = repr(result)
    for forbidden in (_TOKEN, marker.lower(), "DO-NOT-EXPORT-TRANSPORT-DETAIL"):
        assert forbidden not in serialized


class _HttpResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = io.BytesIO(body)

    def __enter__(self) -> _HttpResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)


class _Opener:
    def __init__(self, response: _HttpResponse | Exception) -> None:
        self.response = response
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, *, timeout: float) -> _HttpResponse:
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_https_transport_disables_proxies_rejects_redirect_following_and_uses_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: tuple[object, ...] | None = None
    opener = _Opener(_HttpResponse(b'{"status":"ok"}'))

    def fake_build_opener(*values: object) -> _Opener:
        nonlocal handlers
        handlers = values
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    transport = BoundedHttpsTransport("https://public.example", timeout_seconds=0.5)

    response = transport.get("/api/health")

    assert response == BoundedHttpResponse(200, {"status": "ok"})
    assert handlers is not None
    proxy_handlers = [value for value in handlers if isinstance(value, urllib.request.ProxyHandler)]
    assert len(proxy_handlers) == 1 and proxy_handlers[0].proxies == {}
    assert any(type(value).__name__ == "_NoRedirect" for value in handlers)
    request, timeout = opener.requests[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://public.example/api/health"
    assert timeout <= 0.5


@pytest.mark.parametrize(
    ("origin", "expected_health_url"),
    [
        ("https://203.0.113.7:443", "https://203.0.113.7/api/health"),
        ("https://203.0.113.7:8443", "https://203.0.113.7:8443/api/health"),
        ("https://[2001:db8::7]:443", "https://[2001:db8::7]/api/health"),
        ("https://[2001:db8::7]:8443", "https://[2001:db8::7]:8443/api/health"),
    ],
)
def test_public_probe_routes_canonical_ip_through_real_https_transport(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
    expected_health_url: str,
) -> None:
    opener = _Opener(_HttpResponse(b'{"status":"ok"}'))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: opener)

    probe_public_endpoint(PublicEndpointContext(public_origin=origin))

    request, _timeout = opener.requests[0]
    assert request.full_url == expected_health_url


def test_https_transport_puts_session_only_in_authorization_header() -> None:
    opener = _Opener(_HttpResponse(b'{"status":"ok"}'))
    transport = BoundedHttpsTransport("https://public.example", opener=opener)

    transport.get("/api/auth/check", session_token=_TOKEN)

    request, _timeout = opener.requests[0]
    assert _TOKEN not in request.full_url
    assert request.get_header("Authorization") == f"Bearer {_TOKEN}"
    assert _TOKEN not in repr(transport)


@pytest.mark.parametrize(
    "path",
    [
        "/unknown",
        "api/health",
        "/api/health?token=secret",
        "//evil.example/api/health",
    ],
)
def test_https_transport_rejects_nonfixed_paths(path: str) -> None:
    transport = BoundedHttpsTransport("https://public.example", opener=_Opener(_HttpResponse(b"{}")))

    with pytest.raises(PublicEndpointProbeError, match="invalid public probe path"):
        transport.get(path)


def test_https_transport_rejects_oversized_response_and_timeout_without_detail() -> None:
    oversized = BoundedHttpsTransport(
        "https://public.example",
        max_response_bytes=8,
        opener=_Opener(_HttpResponse(b'{"status":"ok"}')),
    )
    timed_out = BoundedHttpsTransport(
        "https://public.example",
        opener=_Opener(TimeoutError("DO-NOT-EXPORT-TIMEOUT")),
    )

    with pytest.raises(PublicEndpointProbeError, match="response exceeds limit"):
        oversized.get("/api/health")
    with pytest.raises(PublicEndpointProbeError) as captured:
        timed_out.get("/api/health")
    assert "DO-NOT-EXPORT-TIMEOUT" not in str(captured.value)


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"\xff"])
def test_https_transport_preserves_http_status_when_json_is_malformed(body: bytes) -> None:
    error = urllib.error.HTTPError(
        "https://public.example/owner",
        403,
        "forbidden",
        {"Content-Type": "application/json"},
        io.BytesIO(body),
    )
    transport = BoundedHttpsTransport("https://public.example", opener=_Opener(error))

    response = transport.get("/owner")

    assert response == BoundedHttpResponse(status=403, payload=None)


def test_malformed_success_body_is_wrong_product_and_forbidden_success_violation() -> None:
    transport = BoundedHttpsTransport(
        "https://public.example",
        opener=_Opener(_HttpResponse(b"not-json")),
    )

    result = probe_public_endpoint(
        PublicEndpointContext(public_origin="https://public.example"),
        transport=transport,
    )

    assert result.public is PublicState.WRONG_PRODUCT
    assert result.boundary is BoundaryState.VIOLATION
    assert result.code == "public_boundary_violation"


def test_https_transport_reports_redirect_without_following_it() -> None:
    error = urllib.error.HTTPError(
        "https://public.example/owner",
        302,
        "redirect",
        {"Location": "https://evil.example"},
        io.BytesIO(b""),
    )
    transport = BoundedHttpsTransport("https://public.example", opener=_Opener(error))

    response = transport.get("/owner")

    assert response.status == 302
    assert response.redirected is True
    assert response.payload is None
