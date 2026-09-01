from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backend_manager.cloudflared_probe import CloudflaredProbeResult
from backend_manager.config import ManagerConfig, SourceRuntimeConfig
from backend_manager.product_identity import ProductSession
from backend_manager.projection import RuntimeProjection
from backend_manager.public_connectivity import (
    BoundaryState,
    ConnectorState,
    FreshnessState,
    OriginState,
    OverallState,
    OwnershipState,
    PublicState,
    ServiceState,
)
from backend_manager.public_connectivity_provider import (
    PublicConnectivityContext,
    PublicConnectivityProvider,
    PublicConnectivityProviderClosedError,
    build_public_connectivity_provider,
)
from backend_manager.public_endpoint_probe import PublicEndpointProbeResult
from backend_manager.runtime import RuntimeStatus

_START = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _START

    def utcnow(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class _InlineExecutor:
    def __init__(self) -> None:
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(self, function, *args: object) -> Future:
        future: Future = Future()
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(function(*args))
            except BaseException as exc:  # mirror Executor behavior in the test boundary
                future.set_exception(exc)
        return future

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.shutdown_calls.append((wait, cancel_futures))


class _ControlledExecutor:
    def __init__(self) -> None:
        self.tasks: list[tuple[Future, Any, tuple[object, ...]]] = []
        self.shutdown_calls: list[tuple[bool, bool]] = []

    def submit(self, function, *args: object) -> Future:
        future: Future = Future()
        self.tasks.append((future, function, args))
        return future

    def run(self, index: int) -> None:
        future, function, args = self.tasks[index]
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)

    def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
        self.shutdown_calls.append((wait, cancel_futures))
        if cancel_futures:
            for future, _function, _args in self.tasks:
                future.cancel()


def _cloud(
    *,
    ownership: OwnershipState = OwnershipState.EXTERNAL_UNMANAGED,
    service: ServiceState = ServiceState.MISSING,
    connector: ConnectorState = ConnectorState.HEALTHY,
) -> CloudflaredProbeResult:
    return CloudflaredProbeResult(
        ownership=ownership,
        service=service,
        connector=connector,
        cloudflared_version="2026.8.1",
        connection_count=4,
    )


def _public(
    state: PublicState = PublicState.REACHABLE_UNVERIFIED,
    boundary: BoundaryState = BoundaryState.SAFE,
) -> PublicEndpointProbeResult:
    return PublicEndpointProbeResult(state, boundary, "probe-result")


def _context(
    full: bool,
    *,
    origin: OriginState = OriginState.HEALTHY,
    public_origin: str | None = "https://public.example",
    session: ProductSession | None = None,
) -> PublicConnectivityContext:
    return PublicConnectivityContext(
        origin=origin,
        public_origin=public_origin,
        session=session if full else None,
        connector_expectation=None,
    )


def _session() -> ProductSession:
    return ProductSession(
        session_token="tbx-provider-secret",
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at=None,
    )


def test_snapshot_is_cache_only_and_initially_stale_unknown() -> None:
    calls: list[str] = []
    provider = PublicConnectivityProvider(
        context_loader=lambda full: (calls.append(f"context:{full}"), _context(full))[1],
        cloudflared_probe=lambda _expectation: (calls.append("cloud"), _cloud())[1],
        public_endpoint_probe=lambda _context: (calls.append("public"), _public())[1],
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    first = provider.snapshot()
    second = provider.snapshot()

    assert first.overall is OverallState.UNKNOWN
    assert first.freshness is FreshnessState.STALE
    assert first.in_progress is False
    assert second == first
    assert calls == []


def test_manager_restart_does_not_carry_a_prior_healthy_cache() -> None:
    def new_provider() -> PublicConnectivityProvider:
        return PublicConnectivityProvider(
            context_loader=lambda full: _context(full, session=_session()),
            cloudflared_probe=lambda _expectation: _cloud(
                ownership=OwnershipState.MANAGED,
                service=ServiceState.RUNNING,
            ),
            public_endpoint_probe=lambda _context: _public(
                PublicState.AUTHENTICATED_REACHABLE,
            ),
            executor=_InlineExecutor(),
            utcnow=_Clock().utcnow,
        )

    prior_process = new_provider()
    prior_process.request_refresh(full=True)
    assert prior_process.snapshot().overall is OverallState.HEALTHY
    prior_process.shutdown()

    restarted_process = new_provider()
    restarted = restarted_process.snapshot()

    assert restarted.overall is OverallState.UNKNOWN
    assert restarted.freshness is FreshnessState.STALE
    assert restarted.observed_at is None
    restarted_process.shutdown()


def test_local_refresh_maps_probe_axes_without_loading_or_checking_public_session() -> None:
    context_calls: list[bool] = []
    public_calls: list[object] = []
    provider = PublicConnectivityProvider(
        context_loader=lambda full: (context_calls.append(full), _context(full, public_origin=None))[1],
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda context: (public_calls.append(context), _public())[1],
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    generation = provider.request_refresh(full=False)
    status = provider.snapshot()

    assert generation == 1
    assert context_calls == [False]
    assert public_calls == []
    assert status.ownership is OwnershipState.EXTERNAL_UNMANAGED
    assert status.connector is ConnectorState.HEALTHY
    assert status.origin is OriginState.HEALTHY
    assert status.public is PublicState.UNCONFIGURED
    assert status.boundary is BoundaryState.UNKNOWN
    assert status.freshness is FreshnessState.FRESH


def test_full_refresh_is_the_only_path_that_receives_session_and_public_probe() -> None:
    session = _session()
    context_calls: list[bool] = []
    seen_sessions: list[ProductSession | None] = []

    def load_context(full: bool) -> PublicConnectivityContext:
        context_calls.append(full)
        return _context(full, session=session)

    def probe_public(context) -> PublicEndpointProbeResult:
        seen_sessions.append(context.session)
        return _public(PublicState.AUTHENTICATED_REACHABLE)

    provider = PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=probe_public,
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=False)
    provider.request_refresh(full=True)
    status = provider.snapshot()

    assert context_calls == [False, True]
    assert seen_sessions == [session]
    assert status.public is PublicState.AUTHENTICATED_REACHABLE
    assert status.boundary is BoundaryState.SAFE
    assert status.public_checked_at == _START


def test_older_generation_cannot_overwrite_a_newer_completed_generation() -> None:
    executor = _ControlledExecutor()
    calls = 0

    def cloud_probe(_expectation) -> CloudflaredProbeResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _cloud(ownership=OwnershipState.UNCONFIGURED, connector=ConnectorState.UNKNOWN)
        return _cloud(ownership=OwnershipState.EXTERNAL_UNMANAGED)

    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, public_origin=None),
        cloudflared_probe=cloud_probe,
        public_endpoint_probe=lambda _context: _public(),
        executor=executor,
        utcnow=_Clock().utcnow,
    )

    assert provider.request_refresh(full=False) == 1
    assert provider.request_refresh(full=False) == 2
    executor.run(1)
    newer = provider.snapshot()
    executor.run(0)
    after_older = provider.snapshot()

    assert newer.ownership is OwnershipState.UNCONFIGURED
    assert newer.in_progress is False
    assert after_older == newer


def test_local_refresh_does_not_make_an_old_full_public_result_fresh() -> None:
    clock = _Clock()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full),
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=lambda _context: _public(PublicState.AUTHENTICATED_REACHABLE),
        executor=_InlineExecutor(),
        utcnow=clock.utcnow,
        max_age_seconds=60,
    )

    provider.request_refresh(full=True)
    assert provider.snapshot().freshness is FreshnessState.FRESH
    clock.advance(30)
    provider.request_refresh(full=False)
    assert provider.snapshot().observed_at == _START
    clock.advance(31)

    stale = provider.snapshot()
    assert stale.freshness is FreshnessState.STALE
    assert stale.overall is OverallState.UNKNOWN
    assert stale.public_checked_at == _START


def test_full_check_without_session_stays_reachable_unverified() -> None:
    seen: list[ProductSession | None] = []

    def endpoint(context) -> PublicEndpointProbeResult:
        seen.append(context.session)
        return _public(PublicState.REACHABLE_UNVERIFIED)

    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=None),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=endpoint,
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)

    assert seen == [None]
    assert provider.snapshot().public is PublicState.REACHABLE_UNVERIFIED


class _MonitorStop:
    def __init__(self, answers: list[bool]) -> None:
        self.answers = answers
        self.timeouts: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.timeouts.append(timeout)
        return self.answers.pop(0)


def test_monitor_uses_ten_second_cadence() -> None:
    cloud_calls: list[None] = []
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, public_origin=None),
        cloudflared_probe=lambda _expectation: (cloud_calls.append(None), _cloud())[1],
        public_endpoint_probe=lambda _context: _public(),
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
        refresh_interval_seconds=10,
    )
    stop = _MonitorStop([False, True])

    provider.run_monitor(stop)  # type: ignore[arg-type]

    assert stop.timeouts == [10, 10]
    assert cloud_calls == [None]


def test_monitor_does_not_overlap_an_inflight_generation() -> None:
    executor = _ControlledExecutor()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, public_origin=None),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda _context: _public(),
        executor=executor,
        utcnow=_Clock().utcnow,
    )
    provider.request_refresh(full=False)
    stop = _MonitorStop([False, True])

    provider.run_monitor(stop)  # type: ignore[arg-type]

    assert len(executor.tasks) == 1


def test_probe_exception_commits_only_safe_unknown_evidence() -> None:
    marker = "DO-NOT-EXPORT-PROVIDER-EXCEPTION"
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full),
        cloudflared_probe=lambda _expectation: (_ for _ in ()).throw(RuntimeError(marker)),
        public_endpoint_probe=lambda _context: _public(),
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    status = provider.snapshot()

    assert status.overall is OverallState.UNKNOWN
    assert status.in_progress is False
    assert marker not in repr(status)
    assert marker not in repr(status.to_projection())


def test_shutdown_cancels_queued_work_and_rejects_new_requests_without_waiting() -> None:
    executor = _ControlledExecutor()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda _context: _public(),
        executor=executor,
        utcnow=_Clock().utcnow,
    )
    provider.request_refresh(full=False)

    provider.shutdown()

    assert executor.shutdown_calls == [(False, True)]
    assert executor.tasks[0][0].cancelled()
    with pytest.raises(PublicConnectivityProviderClosedError):
        provider.request_refresh(full=False)


class _Runtime:
    def __init__(
        self,
        health_state: str = "healthy",
        healthy: bool = True,
        public_origin: str | None = None,
    ) -> None:
        self.health_state = health_state
        self.healthy = healthy
        self.public_origin = public_origin

    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=self.healthy,
            pid=1,
            uptime_seconds=1,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=0,
            backend_service_state=None,
            database_service_state=None,
            log=[],
            health_state=self.health_state,
            public_origin=self.public_origin,
        )


class _RuntimeProvider:
    mode_hint = "source"

    def __init__(self, config: ManagerConfig, runtime: _Runtime) -> None:
        self.config = config
        self.runtime = runtime
        self.current_calls = 0

    def current(self) -> RuntimeProjection:
        self.current_calls += 1
        return RuntimeProjection(self.config, self.runtime)


def _config(public_origin: str | None = "https://public.example") -> ManagerConfig:
    return ManagerConfig(
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe"), Path("backend")),
        backend_host="127.0.0.1",
        backend_port=8000,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=public_origin,
        expected_backend_version=None,
        expected_installation_id="ticketbox-0123456789abcdef0123456789abcdef",
        health_request_timeout_seconds=1.0,
    )


@pytest.mark.parametrize(
    ("health_state", "healthy", "expected"),
    [
        ("healthy", True, OriginState.HEALTHY),
        ("mismatch", False, OriginState.IDENTITY_MISMATCH),
        ("stopped", False, OriginState.UNREACHABLE),
        ("pending", False, OriginState.UNKNOWN),
    ],
)
def test_builder_maps_existing_attested_runtime_and_loads_wincred_only_for_full(
    health_state: str,
    healthy: bool,
    expected: OriginState,
) -> None:
    attested_origin = "https://public.example" if healthy else None
    runtime_provider = _RuntimeProvider(
        _config(),
        _Runtime(health_state, healthy, public_origin=attested_origin),
    )
    session_loads: list[str] = []
    public_contexts: list[object] = []
    clock = _Clock()
    provider = build_public_connectivity_provider(
        runtime_provider,  # type: ignore[arg-type]
        product_session_loader=lambda installation_id: (session_loads.append(installation_id), _session())[1],
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda context: (public_contexts.append(context), _public())[1],
        executor=_InlineExecutor(),
        utcnow=clock.utcnow,
    )

    provider.request_refresh(full=False)
    assert provider.snapshot().origin is expected
    assert session_loads == []
    assert public_contexts == []

    provider.request_refresh(full=True)
    if attested_origin is None:
        assert session_loads == []
        assert len(public_contexts) == 1
        assert public_contexts[0].public_origin is None
        assert public_contexts[0].session is None
    else:
        assert session_loads == [runtime_provider.config.expected_installation_id]
        assert len(public_contexts) == 1
        assert public_contexts[0].session is not None


def test_builder_uses_attested_runtime_public_origin_when_manager_config_hides_it() -> None:
    runtime_provider = _RuntimeProvider(
        _config(public_origin=None),
        _Runtime(public_origin="https://installed.example"),
    )
    session_loads: list[str] = []
    public_contexts: list[object] = []
    provider = build_public_connectivity_provider(
        runtime_provider,  # type: ignore[arg-type]
        product_session_loader=lambda installation_id: (
            session_loads.append(installation_id),
            _session(),
        )[1],
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda context: (public_contexts.append(context), _public())[1],
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)

    assert session_loads == [runtime_provider.config.expected_installation_id]
    assert len(public_contexts) == 1
    assert public_contexts[0].public_origin == "https://installed.example"
