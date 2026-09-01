"""Installed Windows-service observation contracts."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path

import pytest

from backend_manager import runtime_factory
from backend_manager.config import InstalledRuntimeConfig, ManagerConfig
from backend_manager.health_probe import (
    HealthProbeResult,
    InstalledHealthExpectation,
    _parse_health_payload,
    _sign_challenge,
)
from backend_manager.installation import InstalledLayout, WindowsReleaseConfig
from backend_manager.runtime import RuntimeControlError, ServiceAccessError
from backend_manager.runtime_factory import build_runtime
from backend_manager.windows_service import (
    ServiceSnapshot,
    WindowsServiceGateway,
    WindowsServiceRuntime,
)


class FakeGateway:
    def __init__(self, *, backend: str = "stopped", database: str = "stopped") -> None:
        self.states = {"TicketboxBackend": backend, "TicketboxPg": database}

    def query(self, name: str) -> ServiceSnapshot:
        state = self.states.get(name, "missing")
        return ServiceSnapshot(name=name, state=state, pid=4321 if state == "running" else None)


_HEALTH_ATTESTATION_KEY = "a" * 64
_HEALTH_CHALLENGE = "b" * 64


def _health_payload(
    *,
    installation_id: str = "01234567-89ab-4def-8123-456789abcdef",
    runtime_access_state: str = "available",
    owner_state: str = "configured",
    owner_recovery_channel: str = "managed_host",
    public_origin: str | None = None,
) -> bytes:
    configured = public_origin is not None
    return json.dumps(
        {
            "contract": "ticketbox-installation-health-v3",
            "status": "ok",
            "product": "ticketbox",
            "backend_version": "9.8.7",
            "installation_id": installation_id,
            "runtime_access_state": runtime_access_state,
            "owner_state": owner_state,
            "owner_recovery_channel": owner_recovery_channel,
            "mobile_connectivity": {
                "public_origin": public_origin,
                "mobile_endpoint_state": (
                    "public_configured_unverified" if configured else "local_only"
                ),
                "android_binding_state": (
                    "configured_unverified" if configured else "setup_required"
                ),
                "iphone_upload_state": (
                    "configured_unverified" if configured else "setup_required"
                ),
            },
        },
        separators=(",", ":"),
    ).encode()


def _runtime(
    gateway: FakeGateway,
    *,
    healthy: bool = True,
    health_result: HealthProbeResult | None = None,
) -> WindowsServiceRuntime:
    result = health_result or HealthProbeResult(
        "healthy" if healthy else "pending",
        "verified" if healthy else "waiting",
    )
    return WindowsServiceRuntime(
        gateway=gateway,
        backend_service_name="TicketboxBackend",
        pg_service_name="TicketboxPg",
        health_probe=lambda: result,
    )


def test_status_reports_services_and_redacted_identity_health_without_raw_logs() -> None:
    runtime = _runtime(FakeGateway(backend="running", database="running"))

    status = runtime.status()

    assert status.mode == "installed"
    assert status.running is True
    assert status.healthy is True
    assert status.pid == 4321
    assert status.backend_service_state == "running"
    assert status.database_service_state == "running"
    assert status.auto_restart is True
    assert status.auto_restart_configurable is False
    assert status.service_controls_available is False
    assert status.log[0] == "后端服务 TicketboxBackend：running，PID 4321"
    assert status.log[1] == "PostgreSQL服务 TicketboxPg：running，PID 4321"
    assert status.log[-1] == "日志状态：受保护；管理器不读取或显示后端原始日志。"
    assert status.health_state == "healthy"
    assert status.health_detail == "verified"


def test_status_carries_attested_public_origin_without_logging_it() -> None:
    public_origin = "https://installed.example"
    runtime = _runtime(
        FakeGateway(backend="running", database="running"),
        health_result=HealthProbeResult(
            "healthy",
            "verified",
            public_origin=public_origin,
        ),
    )

    status = runtime.status()

    assert status.public_origin == public_origin
    assert public_origin not in repr(status)
    assert all(public_origin not in line for line in status.log)


def test_health_json_requires_exact_product_version_and_installation_identity() -> None:
    expectation = InstalledHealthExpectation(
        backend_version="9.8.7",
        installation_id="01234567-89ab-4def-8123-456789abcdef",
        attestation_key=_HEALTH_ATTESTATION_KEY,
    )
    random_200 = _parse_health_payload(
        b'{"status":"ok"}',
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation="0" * 64,
    )
    forged = _parse_health_payload(
        json.dumps(json.loads(_health_payload())).encode(),
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation="0" * 64,
    )
    attestation = _sign_challenge(_HEALTH_ATTESTATION_KEY, _HEALTH_CHALLENGE)
    valid = _parse_health_payload(
        _health_payload(public_origin="https://installed.example"),
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation=attestation,
    )
    wrong_install = _parse_health_payload(
        _health_payload(installation_id="ffffffff-ffff-4fff-8fff-ffffffffffff"),
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation=attestation,
    )
    missing_owner = _parse_health_payload(
        _health_payload(owner_state="recovery_required"),
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation=attestation,
    )
    repair_required = _parse_health_payload(
        _health_payload(runtime_access_state="repair_required"),
        expectation,
        challenge=_HEALTH_CHALLENGE,
        attestation=attestation,
    )

    assert random_200.state == "mismatch"
    assert forged.state == "mismatch"
    assert valid.healthy is True
    assert valid.public_origin == "https://installed.example"
    assert valid.mobile_endpoint_state == "public_configured_unverified"
    assert valid.android_binding_state == "configured_unverified"
    assert valid.iphone_upload_state == "configured_unverified"
    assert valid.owner_state == "configured"
    assert wrong_install.state == "mismatch"
    assert missing_owner.healthy is True
    assert missing_owner.owner_state == "recovery_required"
    assert "缺少可用拥有者身份" in missing_owner.detail
    assert repair_required.healthy is True
    assert repair_required.runtime_access_state == "repair_required"

    mismatch_status = _runtime(
        FakeGateway(backend="running", database="running"),
        health_result=wrong_install,
    ).status()
    pending_status = _runtime(
        FakeGateway(backend="running", database="running"),
        health_result=HealthProbeResult("pending", "listener not ready"),
    ).status()
    assert (mismatch_status.healthy, mismatch_status.health_state) == (False, "mismatch")
    assert (pending_status.healthy, pending_status.health_state) == (False, "pending")


@pytest.mark.parametrize("database_state", ["stopped", "missing", "stop_pending"])
def test_status_is_unhealthy_when_database_is_not_running(database_state: str) -> None:
    probed = False

    def probe() -> HealthProbeResult:
        nonlocal probed
        probed = True
        return HealthProbeResult("healthy", "verified")

    runtime = _runtime(FakeGateway(backend="running", database=database_state))
    runtime._health_probe = probe  # noqa: SLF001 - prove DB failure short-circuits HTTP health

    status = runtime.status()

    assert status.running is True
    assert status.healthy is False
    assert database_state in status.health_detail
    assert "PostgreSQL" in status.health_detail
    assert probed is False


def test_status_never_opens_protected_backend_log(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args, **_kwargs):
        raise AssertionError("ordinary GUI attempted to open a protected backend log")

    monkeypatch.setattr(Path, "open", denied)

    status = _runtime(FakeGateway(backend="running", database="running")).status()

    assert status.running is True
    assert status.database_service_state == "running"
    assert status.log[-1] == "日志状态：受保护；管理器不读取或显示后端原始日志。"


def test_status_access_denial_never_recommends_elevating_http_manager() -> None:
    class DeniedGateway(FakeGateway):
        def query(self, name: str) -> ServiceSnapshot:
            raise ctypes.WinError(5)

    with pytest.raises(ServiceAccessError) as error:
        _runtime(DeniedGateway()).status()

    assert "修复安装或服务权限" in str(error.value)
    assert "管理员身份运行" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows SCM API only exists on Windows")
def test_real_gateway_reports_unknown_service_as_missing() -> None:
    snapshot = WindowsServiceGateway().query("TicketboxDefinitelyMissingForContractTest")

    assert snapshot.state == "missing"


def test_installed_manager_runtime_is_observation_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class QueryOnlyGateway:
        def query(self, name: str) -> ServiceSnapshot:
            return ServiceSnapshot(name=name, state="stopped")

    assert not hasattr(WindowsServiceGateway, "start")
    assert not hasattr(WindowsServiceGateway, "stop")
    monkeypatch.setattr(runtime_factory, "WindowsServiceGateway", QueryOnlyGateway)
    layout = InstalledLayout(
        tmp_path / "program",
        tmp_path / "data",
        8000,
        5432,
        "TicketboxBackend",
        "TicketboxPg",
        "9.8.7",
        "11111111-1111-4111-8111-111111111111",
        "a" * 64,
    )
    release = WindowsReleaseConfig(
        backend_service_name=layout.backend_service_name,
        pg_service_name=layout.pg_service_name,
        service_state_timeout_ms=17_000,
        service_poll_interval_ms=125,
        postgres_ready_timeout_ms=23_000,
        backend_ready_timeout_ms=31_000,
        backend_ready_poll_interval_ms=375,
        backend_health_request_timeout_ms=1_750,
    )
    config = ManagerConfig(
        runtime=InstalledRuntimeConfig(layout, release),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=layout.backend_version,
        expected_installation_id=layout.installation_id,
        health_request_timeout_seconds=release.backend_health_request_timeout_seconds,
    )

    runtime = build_runtime(config)

    assert isinstance(runtime, WindowsServiceRuntime)
    assert runtime.status().service_controls_available is False
    for action in (runtime.start, runtime.stop, runtime.restart, runtime.toggle_auto_restart):
        with pytest.raises(RuntimeControlError, match="生命周期控制保持 HOLD"):
            action()
