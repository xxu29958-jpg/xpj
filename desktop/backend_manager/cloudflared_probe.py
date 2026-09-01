"""Read-only Windows SCM and cloudflared diagnostic adapters.

Raw service configuration, command lines, tunnel identifiers, connector
identifiers, and connection records are confined to this module. The public
result contains only the small evidence allowlist consumed by the read model.
"""

from __future__ import annotations

import ctypes
import json
import ntpath
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final, Protocol, TypeVar

from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState

_DEFAULT_SERVICE_NAME: Final = "Cloudflared"
_DEFAULT_DISCOVERY_PORTS: Final = (20241, 20242, 20243, 20244, 20245)
_ALLOWED_PATHS: Final = frozenset({"/ready", "/diag/tunnel"})
_MAX_CONNECTIONS: Final = 16
_VERSION_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")

_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_SERVICE_DOES_NOT_EXIST = 1060
_SC_MANAGER_CONNECT = 0x0001
_SERVICE_QUERY_CONFIG = 0x0001
_SERVICE_QUERY_STATUS = 0x0004
_SC_STATUS_PROCESS_INFO = 0
_SERVICE_CONFIG_FAILURE_ACTIONS = 2

_STATE_NAMES: Final = {
    1: ServiceState.STOPPED,
    2: ServiceState.START_PENDING,
    3: ServiceState.STOP_PENDING,
    4: ServiceState.RUNNING,
}


class CloudflaredProbeError(RuntimeError):
    """A fixed, non-sensitive read failure."""


@dataclass(frozen=True)
class ServiceFailureAction:
    action_type: int
    delay_ms: int


@dataclass(frozen=True)
class ServiceObservation:
    exists: bool
    state: ServiceState
    argv: tuple[str, ...] = field(default=(), repr=False)
    account: str | None = field(default=None, repr=False)
    start_type: int | None = None
    failure_reset_period_seconds: int | None = None
    failure_actions: tuple[ServiceFailureAction, ...] = ()
    executable_version: str | None = None

    @classmethod
    def missing(cls) -> ServiceObservation:
        return cls(exists=False, state=ServiceState.MISSING)


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


@dataclass(frozen=True)
class LoopbackJsonResponse:
    status: int
    payload: dict[str, object]


@dataclass(frozen=True)
class CloudflaredProbeResult:
    ownership: OwnershipState
    service: ServiceState
    connector: ConnectorState
    cloudflared_version: str | None = None
    connection_count: int | None = None
    service_identity_match: bool | None = None
    binary_identity_match: bool | None = None
    tunnel_identity_match: bool | None = None

    def to_safe_evidence(self) -> dict[str, object]:
        return {
            "ownership": self.ownership.value,
            "service": self.service.value,
            "connector": self.connector.value,
            "cloudflared_version": self.cloudflared_version,
            "connection_count": self.connection_count,
            "service_identity_match": self.service_identity_match,
            "binary_identity_match": self.binary_identity_match,
            "tunnel_identity_match": self.tunnel_identity_match,
        }


class ServiceReader(Protocol):
    def read_exact(self, service_name: str) -> ServiceObservation: ...


class CloudflaredTransport(Protocol):
    def get_json(self, url: str) -> LoopbackJsonResponse: ...


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


class _ServiceStatusProcess(ctypes.Structure):
    _fields_ = (
        ("service_type", wintypes.DWORD),
        ("current_state", wintypes.DWORD),
        ("controls_accepted", wintypes.DWORD),
        ("win32_exit_code", wintypes.DWORD),
        ("service_specific_exit_code", wintypes.DWORD),
        ("check_point", wintypes.DWORD),
        ("wait_hint", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("service_flags", wintypes.DWORD),
    )


class _QueryServiceConfigW(ctypes.Structure):
    _fields_ = (
        ("service_type", wintypes.DWORD),
        ("start_type", wintypes.DWORD),
        ("error_control", wintypes.DWORD),
        ("binary_path", wintypes.LPWSTR),
        ("load_order_group", wintypes.LPWSTR),
        ("tag_id", wintypes.DWORD),
        ("dependencies", ctypes.c_void_p),
        ("account", wintypes.LPWSTR),
        ("display_name", wintypes.LPWSTR),
    )


class _ScAction(ctypes.Structure):
    _fields_ = (("action_type", wintypes.DWORD), ("delay_ms", wintypes.DWORD))


class _ServiceFailureActionsW(ctypes.Structure):
    _fields_ = (
        ("reset_seconds", wintypes.DWORD),
        ("reboot_message", wintypes.LPWSTR),
        ("command", wintypes.LPWSTR),
        ("action_count", wintypes.DWORD),
        ("actions", ctypes.POINTER(_ScAction)),
    )


_ConfigInfo = TypeVar("_ConfigInfo", bound=ctypes.Structure)


class WindowsCloudflaredServiceReader:
    """Locale-independent exact-name SCM reader with no mutation access."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise CloudflaredProbeError("Windows SCM observation is unavailable")
        self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        _declare_advapi32(self._advapi)

    def read_exact(self, service_name: str) -> ServiceObservation:
        name = service_name.strip()
        if not name or len(name) > 256 or any(character in name for character in "*?[]"):
            raise CloudflaredProbeError("invalid exact service name")
        try:
            with self._open_service(name) as service:
                status = self._query_status(service)
                base, base_buffer = _query_base(self._advapi, service)
                failure = _query_info(
                    self._advapi,
                    service,
                    _SERVICE_CONFIG_FAILURE_ACTIONS,
                    _ServiceFailureActionsW,
                )
                actions = tuple(
                    ServiceFailureAction(
                        action_type=int(failure.actions[index].action_type),
                        delay_ms=int(failure.actions[index].delay_ms),
                    )
                    for index in range(int(failure.action_count))
                )
                observation = ServiceObservation(
                    exists=True,
                    state=_STATE_NAMES.get(int(status.current_state), ServiceState.FAILED),
                    argv=_command_line_argv(base.binary_path or ""),
                    account=(base.account or "").strip() or None,
                    start_type=int(base.start_type),
                    failure_reset_period_seconds=int(failure.reset_seconds),
                    failure_actions=actions,
                    executable_version=_file_version_from_argv(base.binary_path or ""),
                )
                del base_buffer
                return observation
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_SERVICE_DOES_NOT_EXIST:
                return ServiceObservation.missing()
            raise CloudflaredProbeError("Windows SCM observation failed") from None

    @contextmanager
    def _open_service(self, service_name: str):
        manager = self._advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
        if not manager:
            raise ctypes.WinError(ctypes.get_last_error())
        service = None
        try:
            service = self._advapi.OpenServiceW(
                manager,
                service_name,
                _SERVICE_QUERY_CONFIG | _SERVICE_QUERY_STATUS,
            )
            if not service:
                raise ctypes.WinError(ctypes.get_last_error())
            yield service
        finally:
            if service:
                self._advapi.CloseServiceHandle(service)
            self._advapi.CloseServiceHandle(manager)

    def _query_status(self, service: int) -> _ServiceStatusProcess:
        status = _ServiceStatusProcess()
        needed = wintypes.DWORD()
        if not self._advapi.QueryServiceStatusEx(
            service,
            _SC_STATUS_PROCESS_INFO,
            ctypes.cast(ctypes.byref(status), ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.sizeof(status),
            ctypes.byref(needed),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return status


def _declare_advapi32(advapi32: object) -> None:
    advapi32.OpenSCManagerW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenSCManagerW.restype = wintypes.HANDLE
    advapi32.OpenServiceW.argtypes = (wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD)
    advapi32.OpenServiceW.restype = wintypes.HANDLE
    advapi32.QueryServiceStatusEx.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_ubyte),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceStatusEx.restype = wintypes.BOOL
    advapi32.QueryServiceConfigW.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceConfigW.restype = wintypes.BOOL
    advapi32.QueryServiceConfig2W.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.QueryServiceConfig2W.restype = wintypes.BOOL
    advapi32.CloseServiceHandle.argtypes = (wintypes.HANDLE,)
    advapi32.CloseServiceHandle.restype = wintypes.BOOL


def _query_base(advapi32: object, service: int) -> tuple[_QueryServiceConfigW, object]:
    needed = wintypes.DWORD()
    advapi32.QueryServiceConfigW(service, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfigW(service, buffer, needed.value, ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.cast(buffer, ctypes.POINTER(_QueryServiceConfigW)).contents, buffer


def _query_info(
    advapi32: object,
    service: int,
    level: int,
    structure: type[_ConfigInfo],
) -> _ConfigInfo:
    needed = wintypes.DWORD()
    advapi32.QueryServiceConfig2W(service, level, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or needed.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not advapi32.QueryServiceConfig2W(
        service,
        level,
        buffer,
        needed.value,
        ctypes.byref(needed),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    value = ctypes.cast(buffer, ctypes.POINTER(structure)).contents
    value._buffer = buffer  # type: ignore[attr-defined]
    return value


def _command_line_argv(command_line: str) -> tuple[str, ...]:
    if not command_line:
        return ()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command_line, ctypes.byref(count))
    if not values:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return tuple(values[index] for index in range(count.value))
    finally:
        kernel32.LocalFree(ctypes.cast(values, wintypes.HLOCAL))


def _file_version_from_argv(command_line: str) -> str | None:
    """Read a trusted file version resource without executing the binary."""

    try:
        argv = _command_line_argv(command_line)
    except OSError:
        return None
    if not argv or not ntpath.isabs(argv[0]) or argv[0].startswith(("\\\\", "//")):
        return None
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
        version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version.GetFileVersionInfoW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        )
        version.GetFileVersionInfoW.restype = wintypes.BOOL
        version.VerQueryValueW.argtypes = (
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        )
        version.VerQueryValueW.restype = wintypes.BOOL
        ignored = wintypes.DWORD()
        size = version.GetFileVersionInfoSizeW(argv[0], ctypes.byref(ignored))
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(argv[0], 0, size, buffer):
            return None

        class _FixedFileInfo(ctypes.Structure):
            _fields_ = (
                ("signature", wintypes.DWORD),
                ("struct_version", wintypes.DWORD),
                ("file_version_ms", wintypes.DWORD),
                ("file_version_ls", wintypes.DWORD),
                ("product_version_ms", wintypes.DWORD),
                ("product_version_ls", wintypes.DWORD),
                ("file_flags_mask", wintypes.DWORD),
                ("file_flags", wintypes.DWORD),
                ("file_os", wintypes.DWORD),
                ("file_type", wintypes.DWORD),
                ("file_subtype", wintypes.DWORD),
                ("file_date_ms", wintypes.DWORD),
                ("file_date_ls", wintypes.DWORD),
            )

        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
        if info.signature != 0xFEEF04BD:
            return None
        parts = (
            info.file_version_ms >> 16,
            info.file_version_ms & 0xFFFF,
            info.file_version_ls >> 16,
            info.file_version_ls & 0xFFFF,
        )
        candidate = ".".join(str(part) for part in parts)
        return candidate if _VERSION_PATTERN.fullmatch(candidate) else None
    except (AttributeError, OSError, ValueError):
        return None


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
        connector=(
            connector
            if ready_connector_id == diagnostic_connector_id
            else ConnectorState.TUNNEL_MISMATCH
        ),
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
