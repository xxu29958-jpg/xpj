"""Read-only cloudflared diagnostic transport and evidence composition.

Raw tunnel identifiers, connector identifiers, and connection records are
confined to this module. Windows SCM details stay in the dedicated OS adapter.
The public result contains only the evidence allowlist consumed by the model.
"""

from __future__ import annotations

import json
import ntpath
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from backend_manager.cloudflared_contract import (
    CloudflaredProbeError,
    CloudflaredProbeResult,
    CloudflaredTransport,
    LoopbackJsonResponse,
    ServiceFailureAction,
    ServiceObservation,
    ServiceReader,
)
from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState
from backend_manager.windows_cloudflared_service import WindowsCloudflaredServiceReader

_DEFAULT_SERVICE_NAME: Final = "Cloudflared"
_DEFAULT_DISCOVERY_PORTS: Final = (20241, 20242, 20243, 20244, 20245)
_ALLOWED_PATHS: Final = frozenset({"/ready", "/diag/tunnel"})
_MAX_CONNECTIONS: Final = 16
_VERSION_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")


@dataclass(frozen=True)
class ManagedConnectorExpectation:
    service_name: str
    argv: tuple[str, ...] = field(repr=False)
    account: str = field(repr=False)
    start_type: int
    failure_reset_period_seconds: int
    failure_actions: tuple[ServiceFailureAction, ...]
    metrics_port: int
    tunnel_id: str = field(repr=False)
    connector_id: str = field(repr=False)
    origin_url: str = field(repr=False)
    public_origin: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.service_name.strip() or not self.argv:
            raise ValueError("managed connector expectation is incomplete")
        if not 1 <= self.metrics_port <= 65535:
            raise ValueError("managed connector metrics port is invalid")
        if _canonical_uuid(self.tunnel_id) is None or _canonical_uuid(self.connector_id) is None:
            raise ValueError("managed connector identity is invalid")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class LoopbackCloudflaredTransport:
    """Bounded GET-only transport for a fixed cloudflared loopback surface."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 0.35,
        max_response_bytes: int = 8 * 1024,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes <= 0:
            raise ValueError("cloudflared transport limits must be positive")
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )

    def get_json(self, url: str) -> LoopbackJsonResponse:
        self._validate_url(url)
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status = int(response.status)
                raw = response.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise CloudflaredProbeError("cloudflared redirect rejected") from None
            if exc.code != 503:
                raise CloudflaredProbeError("cloudflared endpoint unavailable") from None
            status = int(exc.code)
            raw = exc.read(self._max_response_bytes + 1)
        except (OSError, TimeoutError, ValueError, urllib.error.URLError):
            raise CloudflaredProbeError("cloudflared loopback request failed") from None
        if len(raw) > self._max_response_bytes:
            raise CloudflaredProbeError("cloudflared response exceeds limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise CloudflaredProbeError("cloudflared response is not valid JSON") from None
        if not isinstance(payload, dict):
            raise CloudflaredProbeError("cloudflared response schema is invalid")
        return LoopbackJsonResponse(status=status, payload=payload)

    @staticmethod
    def _validate_url(url: str) -> None:
        try:
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
        except (TypeError, ValueError):
            port = None
            parsed = urllib.parse.SplitResult("", "", "", "", "")
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or port is None
            or not 1 <= port <= 65535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in _ALLOWED_PATHS
            or parsed.query
            or parsed.fragment
        ):
            raise CloudflaredProbeError("invalid loopback endpoint")


@dataclass(frozen=True)
class _EndpointObservation:
    connector: ConnectorState
    connection_count: int
    tunnel_id: str = field(repr=False)
    connector_id: str = field(repr=False)
    identity_consistent: bool = True


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError):
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def _required_int(value: object, *, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        return None
    return value


def _parse_ready(response: LoopbackJsonResponse) -> tuple[int, str, ConnectorState]:
    payload = response.payload
    if set(payload) != {"status", "readyConnections", "connectorId"}:
        raise CloudflaredProbeError("cloudflared readiness schema is invalid")
    status = _required_int(payload.get("status"), minimum=100, maximum=599)
    count = _required_int(payload.get("readyConnections"), minimum=0, maximum=_MAX_CONNECTIONS)
    connector_id = _canonical_uuid(payload.get("connectorId"))
    if status != response.status or count is None or connector_id is None:
        raise CloudflaredProbeError("cloudflared readiness schema is invalid")
    if (status == 200 and count == 0) or (status == 503 and count != 0) or status not in {200, 503}:
        raise CloudflaredProbeError("cloudflared readiness state is inconsistent")
    if count == 0:
        connector = ConnectorState.DOWN
    elif count >= 4:
        connector = ConnectorState.HEALTHY
    else:
        connector = ConnectorState.DEGRADED
    return count, connector_id, connector


def _parse_tunnel(
    response: LoopbackJsonResponse,
    *,
    expected_count: int,
) -> tuple[str, str]:
    payload = response.payload
    allowed = {"tunnelID", "connectorID", "connections", "icmp_sources"}
    if response.status != 200 or not {"tunnelID", "connectorID", "connections"}.issubset(payload):
        raise CloudflaredProbeError("cloudflared diagnostic schema is invalid")
    if not set(payload).issubset(allowed):
        raise CloudflaredProbeError("cloudflared diagnostic schema is invalid")
    tunnel_id = _canonical_uuid(payload.get("tunnelID"))
    connector_id = _canonical_uuid(payload.get("connectorID"))
    connections = payload.get("connections")
    if (
        tunnel_id is None
        or connector_id is None
        or not isinstance(connections, list)
        or len(connections) != expected_count
        or len(connections) > _MAX_CONNECTIONS
        or any(not isinstance(item, Mapping) for item in connections)
    ):
        raise CloudflaredProbeError("cloudflared diagnostic schema is invalid")
    icmp_sources = payload.get("icmp_sources", [])
    if (
        not isinstance(icmp_sources, list)
        or len(icmp_sources) > 8
        or any(not isinstance(item, str) or len(item) > 128 for item in icmp_sources)
    ):
        raise CloudflaredProbeError("cloudflared diagnostic schema is invalid")
    return tunnel_id, connector_id


def _observe_endpoint(transport: CloudflaredTransport, port: int) -> _EndpointObservation:
    ready = transport.get_json(f"http://127.0.0.1:{port}/ready")
    count, ready_connector_id, connector = _parse_ready(ready)
    tunnel = transport.get_json(f"http://127.0.0.1:{port}/diag/tunnel")
    tunnel_id, diagnostic_connector_id = _parse_tunnel(tunnel, expected_count=count)
    return _EndpointObservation(
        connector=(connector if ready_connector_id == diagnostic_connector_id else ConnectorState.TUNNEL_MISMATCH),
        connection_count=count,
        tunnel_id=tunnel_id,
        connector_id=diagnostic_connector_id,
        identity_consistent=ready_connector_id == diagnostic_connector_id,
    )


def _safe_version(value: str | None) -> str | None:
    return value if value is not None and _VERSION_PATTERN.fullmatch(value) else None


def _normalized_windows_path(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(value.strip().strip('"')))


def _service_matches(
    observation: ServiceObservation,
    expectation: ManagedConnectorExpectation,
) -> tuple[bool, bool]:
    if not observation.exists or not observation.argv:
        return False, False
    binary_match = _normalized_windows_path(observation.argv[0]) == _normalized_windows_path(expectation.argv[0])
    argv_match = observation.argv == expectation.argv
    account_match = (observation.account or "").casefold() == expectation.account.casefold()
    service_match = (
        binary_match
        and argv_match
        and account_match
        and observation.start_type == expectation.start_type
        and observation.failure_reset_period_seconds == expectation.failure_reset_period_seconds
        and observation.failure_actions == expectation.failure_actions
    )
    return service_match, binary_match


def _read_service(reader: ServiceReader, name: str) -> ServiceObservation:
    try:
        return reader.read_exact(name)
    except (CloudflaredProbeError, OSError):
        return ServiceObservation(exists=False, state=ServiceState.UNKNOWN)


def _read_endpoints(
    transport: CloudflaredTransport,
    ports: tuple[int, ...],
) -> list[_EndpointObservation]:
    observations: list[_EndpointObservation] = []
    for port in ports:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            continue
        try:
            observations.append(_observe_endpoint(transport, port))
        except (CloudflaredProbeError, OSError, TimeoutError, ValueError):
            continue
    return observations


def _connector_without_endpoint(service: ServiceObservation) -> ConnectorState:
    if service.state is ServiceState.RUNNING:
        return ConnectorState.DOWN
    if service.state is ServiceState.START_PENDING:
        return ConnectorState.CONNECTING
    return ConnectorState.UNKNOWN


def probe_cloudflared(
    expectation: ManagedConnectorExpectation | None = None,
    *,
    service_reader: ServiceReader | None = None,
    transport: CloudflaredTransport | None = None,
    discovery_ports: tuple[int, ...] = _DEFAULT_DISCOVERY_PORTS,
) -> CloudflaredProbeResult:
    """Observe one exact managed binding or the fixed external discovery set."""

    reader = service_reader or WindowsCloudflaredServiceReader()
    http = transport or LoopbackCloudflaredTransport()
    service_name = expectation.service_name if expectation is not None else _DEFAULT_SERVICE_NAME
    service = _read_service(reader, service_name)
    ports = (expectation.metrics_port,) if expectation is not None else tuple(discovery_ports)
    endpoints = _read_endpoints(http, ports)
    version = _safe_version(service.executable_version)

    if len(endpoints) > 1:
        return CloudflaredProbeResult(
            ownership=OwnershipState.CONFLICT,
            service=service.state,
            connector=ConnectorState.TUNNEL_MISMATCH,
            cloudflared_version=version,
        )

    endpoint = endpoints[0] if endpoints else None
    if expectation is None:
        if endpoint is not None and not endpoint.identity_consistent:
            return CloudflaredProbeResult(
                ownership=OwnershipState.CONFLICT,
                service=service.state,
                connector=ConnectorState.TUNNEL_MISMATCH,
                cloudflared_version=version,
            )
        observed = service.exists or endpoint is not None
        return CloudflaredProbeResult(
            ownership=(OwnershipState.EXTERNAL_UNMANAGED if observed else OwnershipState.UNCONFIGURED),
            service=service.state,
            connector=(endpoint.connector if endpoint is not None else _connector_without_endpoint(service)),
            cloudflared_version=version,
            connection_count=(endpoint.connection_count if endpoint is not None else None),
        )

    service_match, binary_match = _service_matches(service, expectation)
    if service.exists and not service_match:
        return CloudflaredProbeResult(
            ownership=OwnershipState.CONFLICT,
            service=ServiceState.IDENTITY_MISMATCH,
            connector=(endpoint.connector if endpoint is not None else _connector_without_endpoint(service)),
            cloudflared_version=version,
            connection_count=(endpoint.connection_count if endpoint is not None else None),
            service_identity_match=False,
            binary_identity_match=binary_match,
            tunnel_identity_match=None,
        )

    tunnel_match: bool | None = None
    connector = endpoint.connector if endpoint is not None else _connector_without_endpoint(service)
    if endpoint is not None:
        tunnel_match = (
            endpoint.identity_consistent
            and endpoint.tunnel_id == expectation.tunnel_id
            and endpoint.connector_id == expectation.connector_id
        )
        if not tunnel_match:
            connector = ConnectorState.TUNNEL_MISMATCH
    return CloudflaredProbeResult(
        ownership=OwnershipState.MANAGED,
        service=service.state,
        connector=connector,
        cloudflared_version=version,
        connection_count=(endpoint.connection_count if endpoint is not None else None),
        service_identity_match=service_match,
        binary_identity_match=binary_match,
        tunnel_identity_match=tunnel_match,
    )
