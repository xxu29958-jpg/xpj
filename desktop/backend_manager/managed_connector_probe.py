"""Observe the exact installed service, payload and loopback PID without privilege."""

from __future__ import annotations

import json
from pathlib import Path

from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME, expected_service
from ticketbox_lifecycle.policy.windows_scm_contract import require_service_configuration
from ticketbox_lifecycle.runtime.windows_connector_files import CONNECTOR_SID
from ticketbox_lifecycle.runtime.windows_connector_observation import require_metrics_owner
from ticketbox_lifecycle.runtime.windows_connector_scm import ConnectorScm
from ticketbox_lifecycle.runtime.windows_known_folders import ticketbox_install_root, ticketbox_program_data_root
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_shipment import WindowsShipmentVerifier

from backend_manager.cloudflared_contract import CloudflaredProbeError, CloudflaredProbeResult
from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState


def probe_managed_connector(expectation, observe_endpoint) -> CloudflaredProbeResult:
    try:
        return _observe(expectation, observe_endpoint)
    except LifecycleError as exc:
        conflict = isinstance(exc, LifecycleViolation) or exc.code in {"scm_configuration_mismatch", "connector_scm_security_changed"}
        return CloudflaredProbeResult(ownership=OwnershipState.CONFLICT if conflict else OwnershipState.UNKNOWN,
            service=ServiceState.IDENTITY_MISMATCH if conflict else ServiceState.UNKNOWN, connector=ConnectorState.UNKNOWN)
    except (OSError, ValueError):
        return CloudflaredProbeResult(ownership=OwnershipState.UNKNOWN, service=ServiceState.UNKNOWN,
            connector=ConnectorState.UNKNOWN)


def _observe(expectation, observe_endpoint) -> CloudflaredProbeResult:
    if expectation.binding is None or expectation.service_name != SERVICE_NAME:
        raise ValueError("a protected installed binding is required")
    root = ticketbox_install_root()
    WindowsShipmentVerifier(root, ticketbox_program_data_root()).verify_connector_payload(expectation.binding)
    scm = ConnectorScm()
    before = scm.state_pid()
    if before is None:
        require_metrics_owner(None)
        return CloudflaredProbeResult(ownership=OwnershipState.UNKNOWN, service=ServiceState.MISSING,
            connector=ConnectorState.DOWN)
    observer = NativeWindowsScmObserver()
    config = observer.observe(SERVICE_NAME)
    require_service_configuration(SERVICE_NAME, config,
        expected_service(expectation.argv, CONNECTOR_SID, expectation.start_type),
        allowed_start_types=frozenset({expectation.start_type}))
    scm.require_dacl()
    # SCM binds this own-process service to its verified executable and PID.
    # An ordinary user can query SCM and TCP ownership but cannot open a
    # virtual-account service process. Do not turn that into an admin UI.
    # Pending-state PIDs are not valid process identities according to SCM.
    process = before[1] if before[0] == 4 else None
    if before[0] == 4 and not process:
        raise ValueError("running service has no process identity")
    if before[0] in {1, 4}:
        require_metrics_owner(process)
    endpoint = None
    try:
        if process is not None:
            endpoint = observe_endpoint(expectation.metrics_port)
    except (CloudflaredProbeError, TimeoutError):
        pass
    if before[0] in {1, 4}:
        require_metrics_owner(process)
    scm.require_dacl()
    if observer.observe(SERVICE_NAME) != config or scm.state_pid() != before:
        raise ValueError("service configuration or process changed during observation")
    return _observed_result(expectation, before[0], endpoint)


def _observed_result(expectation, service_status: int, endpoint) -> CloudflaredProbeResult:
    version = json.loads((Path(expectation.argv[0]).parent / "profile.json").read_text("utf-8"))["version"]
    service_state = {1: ServiceState.STOPPED, 2: ServiceState.START_PENDING, 3: ServiceState.STOP_PENDING,
        4: ServiceState.RUNNING}.get(service_status, ServiceState.UNKNOWN)
    tunnel_match = endpoint.identity_consistent and endpoint.tunnel_id == expectation.tunnel_id if endpoint else None
    connector = endpoint.connector if endpoint else (ConnectorState.DOWN if service_status in {1, 4} else ConnectorState.UNKNOWN)
    if tunnel_match is False:
        connector = ConnectorState.TUNNEL_MISMATCH
    return CloudflaredProbeResult(ownership=OwnershipState.CONFLICT if tunnel_match is False else OwnershipState.MANAGED,
        service=service_state, connector=connector, cloudflared_version=version,
        connection_count=endpoint.connection_count if endpoint else None,
        service_identity_match=True, binary_identity_match=True, tunnel_identity_match=tunnel_match)
