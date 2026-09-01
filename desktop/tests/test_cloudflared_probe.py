from __future__ import annotations

import io
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from backend_manager.cloudflared_probe import (
    CloudflaredProbeError,
    LoopbackCloudflaredTransport,
    LoopbackJsonResponse,
    ManagedConnectorExpectation,
    ServiceFailureAction,
    ServiceObservation,
    probe_cloudflared,
)
from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState

_TUNNEL_ID = "11111111-2222-4333-8444-555555555555"
_CONNECTOR_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_OTHER_TUNNEL_ID = "99999999-2222-4333-8444-555555555555"
_OTHER_CONNECTOR_ID = "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_EXPECTED_ARGV = (
    r"C:\Program Files\Ticketbox\connector\cloudflared.exe",
    "tunnel",
    "--no-autoupdate",
    "--metrics",
    "127.0.0.1:24001",
    "run",
    "--token-file",
    r"C:\ProgramData\Ticketbox\machine-secrets\connector-token",
)
_FAILURE_ACTIONS = (
    ServiceFailureAction(action_type=1, delay_ms=1000),
    ServiceFailureAction(action_type=1, delay_ms=5000),
    ServiceFailureAction(action_type=0, delay_ms=0),
)


def _expectation(**changes: object) -> ManagedConnectorExpectation:
    baseline = ManagedConnectorExpectation(
        service_name="TicketboxPublicConnector",
        argv=_EXPECTED_ARGV,
        account="LocalSystem",
        start_type=2,
        failure_reset_period_seconds=86400,
        failure_actions=_FAILURE_ACTIONS,
        metrics_port=24001,
        tunnel_id=_TUNNEL_ID,
        connector_id=_CONNECTOR_ID,
        origin_url="http://127.0.0.1:8000",
        public_origin="https://ticketbox.invalid",
    )
    return replace(baseline, **changes)


def _service(**changes: object) -> ServiceObservation:
    baseline = ServiceObservation(
        exists=True,
        state=ServiceState.RUNNING,
        argv=_EXPECTED_ARGV,
        account="LocalSystem",
        start_type=2,
        failure_reset_period_seconds=86400,
        failure_actions=_FAILURE_ACTIONS,
        executable_version="2026.8.1",
    )
    return replace(baseline, **changes)


def _ready(
    *,
    status: int = 200,
    count: int = 4,
    connector_id: str = _CONNECTOR_ID,
) -> LoopbackJsonResponse:
    return LoopbackJsonResponse(
        status=status,
        payload={"status": status, "readyConnections": count, "connectorId": connector_id},
    )


def _tunnel(
    *,
    tunnel_id: str = _TUNNEL_ID,
    connector_id: str = _CONNECTOR_ID,
    count: int = 4,
) -> LoopbackJsonResponse:
    return LoopbackJsonResponse(
        status=200,
        payload={
            "tunnelID": tunnel_id,
            "connectorID": connector_id,
            "connections": [{} for _ in range(count)],
        },
    )


class _ServiceReader:
    def __init__(self, observation: ServiceObservation | Exception) -> None:
        self.observation = observation
        self.names: list[str] = []

    def read_exact(self, service_name: str) -> ServiceObservation:
        self.names.append(service_name)
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation


class _Transport:
    def __init__(self, responses: dict[str, LoopbackJsonResponse | Exception]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get_json(self, url: str) -> LoopbackJsonResponse:
        self.urls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _responses(
    port: int = 24001,
    *,
    ready: LoopbackJsonResponse | Exception | None = None,
    tunnel: LoopbackJsonResponse | Exception | None = None,
) -> dict[str, LoopbackJsonResponse | Exception]:
    return {
        f"http://127.0.0.1:{port}/ready": ready or _ready(),
        f"http://127.0.0.1:{port}/diag/tunnel": tunnel or _tunnel(),
    }


def test_absent_exact_service_and_diagnostics_are_unconfigured() -> None:
    reader = _ServiceReader(ServiceObservation.missing())
    transport = _Transport(
        {f"http://127.0.0.1:{port}/ready": CloudflaredProbeError("unavailable") for port in range(20241, 20246)}
    )

    result = probe_cloudflared(service_reader=reader, transport=transport)

    assert reader.names == ["Cloudflared"]
    assert result.ownership is OwnershipState.UNCONFIGURED
    assert result.service is ServiceState.MISSING
    assert result.connector is ConnectorState.UNKNOWN
    assert result.connection_count is None


def test_unreadable_service_and_diagnostics_keep_ownership_unknown() -> None:
    transport = _Transport(
        {f"http://127.0.0.1:{port}/ready": CloudflaredProbeError("unavailable") for port in range(20241, 20246)}
    )

    result = probe_cloudflared(
        service_reader=_ServiceReader(CloudflaredProbeError("SCM access denied")),
        transport=transport,
    )

    assert result.ownership is OwnershipState.UNKNOWN
    assert result.service is ServiceState.UNKNOWN
    assert result.connector is ConnectorState.UNKNOWN


def test_external_ready_connector_never_becomes_managed() -> None:
    reader = _ServiceReader(ServiceObservation.missing())
    responses: dict[str, LoopbackJsonResponse | Exception] = {
        f"http://127.0.0.1:{port}/ready": CloudflaredProbeError("unavailable") for port in range(20241, 20246)
    }
    responses.update(_responses(20243))

    result = probe_cloudflared(service_reader=reader, transport=_Transport(responses))

    assert result.ownership is OwnershipState.EXTERNAL_UNMANAGED
    assert result.service is ServiceState.MISSING
    assert result.connector is ConnectorState.HEALTHY
    assert result.connection_count == 4
    assert result.service_identity_match is None
    assert result.binary_identity_match is None
    assert result.tunnel_identity_match is None


def test_protected_expectation_requires_every_service_and_tunnel_identity() -> None:
    reader = _ServiceReader(_service())

    result = probe_cloudflared(
        _expectation(),
        service_reader=reader,
        transport=_Transport(_responses()),
    )

    assert reader.names == ["TicketboxPublicConnector"]
    assert result.ownership is OwnershipState.MANAGED
    assert result.service is ServiceState.RUNNING
    assert result.connector is ConnectorState.HEALTHY
    assert result.cloudflared_version == "2026.8.1"
    assert result.connection_count == 4
    assert result.service_identity_match is True
    assert result.binary_identity_match is True
    assert result.tunnel_identity_match is True


@pytest.mark.parametrize(
    ("service_observation", "expected_service"),
    [
        (ServiceObservation.missing(), ServiceState.MISSING),
        (CloudflaredProbeError("SCM access denied"), ServiceState.UNKNOWN),
    ],
)
def test_protected_expectation_without_complete_evidence_is_not_managed(
    service_observation: ServiceObservation | Exception,
    expected_service: ServiceState,
) -> None:
    result = probe_cloudflared(
        _expectation(),
        service_reader=_ServiceReader(service_observation),
        transport=_Transport(
            {"http://127.0.0.1:24001/ready": CloudflaredProbeError("unavailable")}
        ),
    )

    assert result.ownership is OwnershipState.UNKNOWN
    assert result.service is expected_service
    assert result.service_identity_match is False
    assert result.tunnel_identity_match is None


def test_image_path_or_argv_mismatch_is_an_identity_conflict_without_path_leak() -> None:
    marker = "DO-NOT-EXPORT-SECRET-PATH"
    wrong = _service(argv=(rf"C:\{marker}\cloudflared.exe", *_EXPECTED_ARGV[1:]))

    result = probe_cloudflared(
        _expectation(),
        service_reader=_ServiceReader(wrong),
        transport=_Transport(_responses()),
    )

    assert result.ownership is OwnershipState.CONFLICT
    assert result.service is ServiceState.IDENTITY_MISMATCH
    assert result.binary_identity_match is False
    assert marker not in repr(result)
    assert marker not in repr(result.to_safe_evidence())


@pytest.mark.parametrize(
    "observation",
    [
        _service(account="NT AUTHORITY\\NetworkService"),
        _service(start_type=3),
        _service(failure_reset_period_seconds=0),
        _service(failure_actions=(ServiceFailureAction(action_type=0, delay_ms=0),)),
    ],
)
def test_scm_contract_mismatch_is_never_managed(observation: ServiceObservation) -> None:
    result = probe_cloudflared(
        _expectation(),
        service_reader=_ServiceReader(observation),
        transport=_Transport(_responses()),
    )

    assert result.ownership is OwnershipState.CONFLICT
    assert result.service is ServiceState.IDENTITY_MISMATCH
    assert result.service_identity_match is False


def test_expected_tunnel_mismatch_is_connector_unavailable_not_false_healthy() -> None:
    result = probe_cloudflared(
        _expectation(),
        service_reader=_ServiceReader(_service()),
        transport=_Transport(_responses(tunnel=_tunnel(tunnel_id=_OTHER_TUNNEL_ID))),
    )

    assert result.ownership is OwnershipState.CONFLICT
    assert result.service is ServiceState.RUNNING
    assert result.connector is ConnectorState.TUNNEL_MISMATCH
    assert result.tunnel_identity_match is False


def test_ready_and_diagnostic_connector_ids_must_match_each_other() -> None:
    result = probe_cloudflared(
        service_reader=_ServiceReader(ServiceObservation.missing()),
        transport=_Transport(
            {
                **{
                    f"http://127.0.0.1:{port}/ready": CloudflaredProbeError("unavailable")
                    for port in range(20241, 20246)
                },
                **_responses(20241, tunnel=_tunnel(connector_id=_OTHER_CONNECTOR_ID)),
            }
        ),
    )

    assert result.ownership is OwnershipState.CONFLICT
    assert result.connector is ConnectorState.TUNNEL_MISMATCH


def test_multiple_distinct_diagnostic_identities_are_a_conflict() -> None:
    responses: dict[str, LoopbackJsonResponse | Exception] = {
        f"http://127.0.0.1:{port}/ready": CloudflaredProbeError("unavailable") for port in range(20241, 20246)
    }
    responses.update(_responses(20241))
    responses.update(
        _responses(
            20242,
            ready=_ready(connector_id=_OTHER_CONNECTOR_ID),
            tunnel=_tunnel(tunnel_id=_OTHER_TUNNEL_ID, connector_id=_OTHER_CONNECTOR_ID),
        )
    )

    result = probe_cloudflared(
        service_reader=_ServiceReader(ServiceObservation.missing()),
        transport=_Transport(responses),
    )

    assert result.ownership is OwnershipState.CONFLICT
    assert result.connector is ConnectorState.TUNNEL_MISMATCH
    assert result.connection_count is None


@pytest.mark.parametrize(
    "tunnel",
    [
        LoopbackJsonResponse(status=200, payload={"tunnelID": "not-a-uuid", "connectorID": _CONNECTOR_ID}),
        LoopbackJsonResponse(
            status=200,
            payload={"tunnelID": _TUNNEL_ID, "connectorID": _CONNECTOR_ID, "connections": "four"},
        ),
        LoopbackJsonResponse(
            status=200,
            payload={
                "tunnelID": _TUNNEL_ID,
                "connectorID": _CONNECTOR_ID,
                "connections": [{}, {}, {}],
            },
        ),
    ],
)
def test_malformed_or_inconsistent_diagnostic_payload_fails_closed(
    tunnel: LoopbackJsonResponse,
) -> None:
    result = probe_cloudflared(
        service_reader=_ServiceReader(ServiceObservation.missing()),
        transport=_Transport(_responses(20241, tunnel=tunnel)),
        discovery_ports=(20241,),
    )

    assert result.connector is ConnectorState.UNKNOWN
    assert result.ownership is OwnershipState.UNCONFIGURED


@pytest.mark.parametrize(
    ("ready", "expected"),
    [
        (_ready(status=503, count=0), ConnectorState.DOWN),
        (_ready(status=200, count=1), ConnectorState.DEGRADED),
        (_ready(status=200, count=3), ConnectorState.DEGRADED),
        (_ready(status=200, count=4), ConnectorState.HEALTHY),
    ],
)
def test_connector_state_uses_readiness_connection_count(
    ready: LoopbackJsonResponse,
    expected: ConnectorState,
) -> None:
    result = probe_cloudflared(
        service_reader=_ServiceReader(ServiceObservation.missing()),
        transport=_Transport(_responses(20241, ready=ready, tunnel=_tunnel(count=ready.payload["readyConnections"]))),
        discovery_ports=(20241,),
    )

    assert result.connector is expected


def test_safe_evidence_and_repr_never_expose_ids_argv_or_origins() -> None:
    marker = "DO-NOT-EXPORT-CONNECTOR-SECRET"
    expectation = _expectation(
        argv=(*_EXPECTED_ARGV, marker),
        public_origin=f"https://{marker}.invalid",
    )
    observation = _service(argv=expectation.argv)
    result = probe_cloudflared(
        expectation,
        service_reader=_ServiceReader(observation),
        transport=_Transport(_responses()),
    )

    serialized = repr(result) + repr(result.to_safe_evidence())
    for forbidden in (marker, _TUNNEL_ID, _CONNECTOR_ID, "Program Files", "machine-secrets"):
        assert forbidden not in serialized


class _HttpResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
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
        self.requests: list[tuple[str, float]] = []

    def open(self, request: urllib.request.Request, *, timeout: float) -> _HttpResponse:
        self.requests.append((request.full_url, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:20241/ready",
        "http://0.0.0.0:20241/ready",
        "http://192.168.1.8:20241/ready",
        "https://127.0.0.1:20241/ready",
        "http://127.0.0.1:20241/metrics",
        "http://127.0.0.1:20241/ready?token=secret",
        "http://user@127.0.0.1:20241/ready",
    ],
)
def test_loopback_transport_rejects_every_non_exact_url(url: str) -> None:
    transport = LoopbackCloudflaredTransport(opener=_Opener(_HttpResponse(b"{}")))

    with pytest.raises(CloudflaredProbeError, match="invalid loopback endpoint"):
        transport.get_json(url)


def test_loopback_transport_disables_proxies_and_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers: tuple[object, ...] | None = None

    def fake_build_opener(*values: object) -> _Opener:
        nonlocal handlers
        handlers = values
        return _Opener(
            _HttpResponse(
                b'{"status":503,"readyConnections":0,"connectorId":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"}', status=503
            )
        )

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    transport = LoopbackCloudflaredTransport(timeout_seconds=0.25)

    response = transport.get_json("http://127.0.0.1:20241/ready")

    assert response.status == 503
    assert handlers is not None
    proxy_handlers = [value for value in handlers if isinstance(value, urllib.request.ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert any(type(value).__name__ == "_NoRedirect" for value in handlers)


def test_loopback_transport_rejects_oversized_and_redirected_responses() -> None:
    oversized = LoopbackCloudflaredTransport(
        max_response_bytes=16,
        opener=_Opener(_HttpResponse(b"{" + (b"x" * 30) + b"}")),
    )
    redirected = LoopbackCloudflaredTransport(
        opener=_Opener(
            urllib.error.HTTPError(
                "http://127.0.0.1:20241/ready",
                302,
                "redirect",
                {},
                io.BytesIO(b"{}"),
            )
        ),
    )

    with pytest.raises(CloudflaredProbeError, match="response exceeds limit"):
        oversized.get_json("http://127.0.0.1:20241/ready")
    with pytest.raises(CloudflaredProbeError, match="redirect rejected"):
        redirected.get_json("http://127.0.0.1:20241/ready")


def test_transport_timeout_is_sanitized() -> None:
    transport = LoopbackCloudflaredTransport(opener=_Opener(TimeoutError("SECRET-TIMEOUT-MARKER")))

    with pytest.raises(CloudflaredProbeError) as captured:
        transport.get_json("http://127.0.0.1:20241/ready")

    assert "SECRET-TIMEOUT-MARKER" not in str(captured.value)
