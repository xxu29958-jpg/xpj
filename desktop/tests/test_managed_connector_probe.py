"""Managed observation trusts exact SCM/PID ownership, never a live port alone."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from ticketbox_lifecycle.policy.connector_profile import SERVICE_NAME, expected_service, service_argv
from ticketbox_lifecycle.runtime import windows_connector_observation
from ticketbox_lifecycle.runtime.windows_connector_files import CONNECTOR_SID

from backend_manager import cloudflared_probe, managed_connector_probe
from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState


@pytest.mark.parametrize("case", ["running", "foreign_listener", "public_listener", "wrong_image", "config_changed", "pid_changed", "stopped", "pending"])
def test_ordinary_observation_requires_the_installed_own_process_and_stable_listener(monkeypatch, tmp_path, case):
    connector = tmp_path / "connector"
    connector.mkdir()
    (connector / "profile.json").write_text(json.dumps({"version": "fixture-version"}), encoding="utf-8")
    argv = service_argv(tmp_path, tmp_path / "secrets", 2)
    expected = SimpleNamespace(binding=object(), service_name=SERVICE_NAME, argv=argv, start_type=2,
        metrics_port=20241, tunnel_id="55555555-5555-4555-8555-555555555555")
    configuration = expected_service(argv, CONNECTOR_SID, 2)
    state = (1, 0) if case == "stopped" else (2, 99) if case == "pending" else (4, 41)
    facts = SimpleNamespace(status_reads=0, config_reads=0, endpoint_reads=0, payload_checks=0)

    class Scm:
        def state_pid(self):
            facts.status_reads += 1
            return (4, 42) if case == "pid_changed" and facts.status_reads > 1 else state

        def require_dacl(self):
            return None

    class Observer:
        def observe(self, _name):
            facts.config_reads += 1
            if case == "wrong_image" or case == "config_changed" and facts.config_reads > 1:
                return replace(configuration, argv=("C:/other/cloudflared.exe", *argv[1:]))
            return configuration

    class Shipment:
        def __init__(self, *_args):
            pass

        def verify_connector_payload(self, binding):
            assert binding is expected.binding
            facts.payload_checks += 1

    def endpoint(_transport, port):
        assert port == 20241
        facts.endpoint_reads += 1
        return SimpleNamespace(identity_consistent=True, tunnel_id=expected.tunnel_id,
            connector=ConnectorState.HEALTHY, connection_count=4)

    def forbidden_process_query(*_args):
        raise AssertionError("ordinary observation must not require opening the service process")

    listeners = [] if case in {"stopped", "pending"} else [("0.0.0.0" if case == "public_listener" else "127.0.0.1", 99 if case == "foreign_listener" else 41)]
    monkeypatch.setattr(windows_connector_observation, "metrics_listeners", lambda: listeners)
    monkeypatch.setattr(windows_connector_observation, "require_process_image", forbidden_process_query)
    monkeypatch.setattr(managed_connector_probe, "ticketbox_install_root", lambda: tmp_path)
    monkeypatch.setattr(managed_connector_probe, "ticketbox_program_data_root", lambda: tmp_path)
    monkeypatch.setattr(managed_connector_probe, "WindowsShipmentVerifier", Shipment)
    monkeypatch.setattr(managed_connector_probe, "ConnectorScm", Scm)
    monkeypatch.setattr(managed_connector_probe, "NativeWindowsScmObserver", Observer)
    monkeypatch.setattr(cloudflared_probe, "_observe_endpoint", endpoint)
    result = cloudflared_probe.probe_cloudflared(expected, transport=object())
    assert facts.payload_checks == 1
    if case in {"foreign_listener", "public_listener", "wrong_image"}:
        assert result.ownership == OwnershipState.CONFLICT and facts.endpoint_reads == 0
    elif case in {"config_changed", "pid_changed"}:
        assert result.ownership == OwnershipState.UNKNOWN
    else:
        assert result.ownership == OwnershipState.MANAGED
        assert result.binary_identity_match is True and result.service_identity_match is True
        if case == "running":
            assert result.connector == ConnectorState.HEALTHY and result.tunnel_identity_match is True
        else:
            assert facts.endpoint_reads == 0
            assert result.service == (ServiceState.STOPPED if case == "stopped" else ServiceState.START_PENDING)
