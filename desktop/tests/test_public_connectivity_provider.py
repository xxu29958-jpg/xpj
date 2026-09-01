from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from backend_manager.cloudflared_probe import CloudflaredProbeResult
from backend_manager.config import ManagerConfig, SourceRuntimeConfig
from backend_manager.product_identity import ProductSession
from backend_manager.product_recovery import RebindRecovery
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
from backend_manager.public_endpoint_probe import PublicEndpointContext, PublicEndpointProbeResult
from backend_manager.runtime import RuntimeStatus

_START = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
_RECOVERY_ATTEMPT_ID = "12345678-1234-5678-1234-567812345678"
_RECOVERY_ATTEMPT_SECRET = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
_RECOVERY_SESSION_TOKEN = "tbx_-4F5emta7ZWJsn1RO0Ujfoy5hD1uW5EXWYsuQ0_IUVw"


class _Clock:
    def __init__(self) -> None:
        self.now = _START
        self.elapsed = 0.0

    def utcnow(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.elapsed += seconds

    def adjust_wall(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def advance_elapsed(self, seconds: float) -> None:
        self.elapsed += seconds


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
    public_origin_authority_known: bool = True,
    session: ProductSession | None = None,
) -> PublicConnectivityContext:
    return PublicConnectivityContext(
        origin=origin,
        public_origin=public_origin,
        public_origin_configured=(
            public_origin is not None if public_origin_authority_known else None
        ),
        session=session if full else None,
        connector_expectation=None,
    )


def _session(session_token: str = "tbx-provider-secret") -> ProductSession:
    return ProductSession(
        session_token=session_token,
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
        expires_at=None,
    )


def _completed_recovery() -> RebindRecovery:
    return RebindRecovery(
        activation_attempt_id=_RECOVERY_ATTEMPT_ID,
        activation_attempt_secret=_RECOVERY_ATTEMPT_SECRET,
        account_name="我",
        ledger_id="owner",
        ledger_name="我的小票夹",
        device_name="小票夹 Desktop",
        role="owner",
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


def test_product_session_invalidation_physically_retires_cached_auth_evidence() -> None:
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=_session()),
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=lambda _context: _public(
            PublicState.AUTHENTICATED_REACHABLE,
            BoundaryState.SAFE,
        ),
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    assert provider.snapshot().public is PublicState.AUTHENTICATED_REACHABLE

    provider.invalidate_product_session()
    invalidated = provider.snapshot()
    provider.request_refresh(full=False)
    after_local_refresh = provider.snapshot()

    assert invalidated.public is PublicState.UNKNOWN
    assert invalidated.boundary is BoundaryState.UNKNOWN
    assert invalidated.public_checked_at is None
    assert invalidated.freshness is FreshnessState.STALE
    assert after_local_refresh.public is PublicState.UNKNOWN
    assert after_local_refresh.boundary is BoundaryState.UNKNOWN
    assert after_local_refresh.public_checked_at is None


def test_product_session_invalidation_blocks_an_inflight_old_session_result() -> None:
    executor = _ControlledExecutor()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=_session()),
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=lambda _context: _public(PublicState.AUTHENTICATED_REACHABLE),
        executor=executor,
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    provider.invalidate_product_session()
    executor.run(0)

    status = provider.snapshot()
    assert status.public is PublicState.UNKNOWN
    assert status.boundary is BoundaryState.UNKNOWN
    assert status.public_checked_at is None
    assert status.in_progress is False


def test_product_session_mutation_window_blocks_refresh_until_the_session_settles() -> None:
    executor = _ControlledExecutor()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=_session()),
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=lambda _context: _public(PublicState.AUTHENTICATED_REACHABLE),
        executor=executor,
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    executor.run(0)
    cached = provider.snapshot()
    assert cached.public is PublicState.AUTHENTICATED_REACHABLE
    assert cached.boundary is BoundaryState.SAFE
    assert cached.public_checked_at is not None

    # Capture a second full check before the session transition. The begin edge
    # must both retire the cached green and prevent this old worker publishing.
    provider.request_refresh(full=True)
    provider.begin_product_session_mutation()
    executor.run(1)
    retired = provider.snapshot()
    assert retired.public is PublicState.UNKNOWN
    assert retired.boundary is BoundaryState.UNKNOWN
    assert retired.public_checked_at is None
    assert retired.freshness is FreshnessState.STALE

    blocked_generation = provider.request_refresh(full=True)

    assert len(executor.tasks) == 2
    assert provider.snapshot().public is PublicState.UNKNOWN

    provider.end_product_session_mutation()
    accepted_generation = provider.request_refresh(full=True)
    executor.run(2)

    assert accepted_generation > blocked_generation
    assert provider.snapshot().public is PublicState.AUTHENTICATED_REACHABLE


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
        monotonic=clock.monotonic,
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


@pytest.mark.parametrize(
    ("changed_origin", "expected_public"),
    [
        (None, PublicState.UNCONFIGURED),
        ("https://changed.example", PublicState.UNKNOWN),
    ],
)
def test_local_refresh_drops_cached_public_evidence_when_origin_changes(
    changed_origin: str | None,
    expected_public: PublicState,
) -> None:
    current_origin: str | None = "https://original.example"
    public_calls: list[str | None] = []

    def load_context(full: bool) -> PublicConnectivityContext:
        return _context(full, public_origin=current_origin, session=_session())

    def probe_public(context: PublicEndpointContext) -> PublicEndpointProbeResult:
        public_calls.append(context.public_origin)
        return _public(PublicState.AUTHENTICATED_REACHABLE, BoundaryState.VIOLATION)

    provider = PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=probe_public,
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    assert provider.snapshot().boundary is BoundaryState.VIOLATION
    current_origin = changed_origin
    provider.request_refresh(full=False)

    status = provider.snapshot()
    assert public_calls == ["https://original.example"]
    assert status.public is expected_public
    assert status.boundary is BoundaryState.UNKNOWN
    assert status.public_checked_at is None


def test_local_refresh_drops_cached_evidence_when_origin_authority_is_lost() -> None:
    authority_known = True

    def load_context(full: bool) -> PublicConnectivityContext:
        return _context(
            full,
            public_origin="https://public.example" if authority_known else None,
            public_origin_authority_known=authority_known,
            session=_session(),
        )

    provider = PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda _context: _public(
            PublicState.AUTHENTICATED_REACHABLE,
            BoundaryState.VIOLATION,
        ),
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    assert provider.snapshot().boundary is BoundaryState.VIOLATION

    authority_known = False
    provider.request_refresh(full=False)
    status = provider.snapshot()

    assert status.public is PublicState.UNKNOWN
    assert status.boundary is BoundaryState.UNKNOWN
    assert status.public_checked_at is None


def test_context_loader_exception_commits_unknown_and_releases_refresh() -> None:
    marker = "DO-NOT-EXPORT-CONTEXT-LOADER-EXCEPTION"
    provider = PublicConnectivityProvider(
        context_loader=lambda _full: (_ for _ in ()).throw(RuntimeError(marker)),
        cloudflared_probe=lambda _expectation: _cloud(),
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


def test_authority_loader_exception_invalidates_cached_public_evidence() -> None:
    authority_available = True
    public_calls: list[str | None] = []

    def load_context(full: bool) -> PublicConnectivityContext:
        if not authority_available:
            raise RuntimeError("runtime authority unavailable")
        return _context(full, public_origin="https://public.example", session=_session())

    def probe_public(context: PublicEndpointContext) -> PublicEndpointProbeResult:
        public_calls.append(context.public_origin)
        return _public(PublicState.AUTHENTICATED_REACHABLE, BoundaryState.VIOLATION)

    provider = PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=probe_public,
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    assert provider.snapshot().boundary is BoundaryState.VIOLATION

    authority_available = False
    provider.request_refresh(full=False)
    lost = provider.snapshot()

    authority_available = True
    provider.request_refresh(full=False)
    recovered = provider.snapshot()

    assert lost.public is PublicState.UNKNOWN
    assert lost.boundary is BoundaryState.UNKNOWN
    assert lost.public_checked_at is None
    assert recovered.public is PublicState.UNKNOWN
    assert recovered.boundary is BoundaryState.UNKNOWN
    assert recovered.public_checked_at is None
    assert public_calls == ["https://public.example"]


def test_newer_refresh_cannot_reuse_cache_after_inflight_authority_loss() -> None:
    executor = _ControlledExecutor()
    authority_known = True
    cloud_calls = 0
    authority_loss_observed = Event()
    release_lost_refresh = Event()

    def load_context(full: bool) -> PublicConnectivityContext:
        return _context(
            full,
            public_origin="https://public.example" if authority_known else None,
            public_origin_authority_known=authority_known,
            session=_session(),
        )

    def cloud_probe(_expectation) -> CloudflaredProbeResult:
        nonlocal cloud_calls
        cloud_calls += 1
        if cloud_calls == 2:
            authority_loss_observed.set()
            release_lost_refresh.wait(timeout=2)
        return _cloud()

    provider = PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=cloud_probe,
        public_endpoint_probe=lambda _context: _public(
            PublicState.AUTHENTICATED_REACHABLE,
            BoundaryState.VIOLATION,
        ),
        executor=executor,
        utcnow=_Clock().utcnow,
    )
    blocked_worker: Thread | None = None
    try:
        provider.request_refresh(full=True)
        executor.run(0)
        assert provider.snapshot().boundary is BoundaryState.VIOLATION

        authority_known = False
        provider.request_refresh(full=False)
        blocked_worker = Thread(target=executor.run, args=(1,))
        blocked_worker.start()
        assert authority_loss_observed.wait(timeout=1)

        authority_known = True
        provider.request_refresh(full=False)
        executor.run(2)

        recovered = provider.snapshot()
        assert recovered.public is PublicState.UNKNOWN
        assert recovered.boundary is BoundaryState.UNKNOWN
        assert recovered.public_checked_at is None
    finally:
        release_lost_refresh.set()
        if blocked_worker is not None:
            blocked_worker.join(timeout=2)
        provider.shutdown()


def test_overlapping_refresh_retires_reusable_public_cache_before_scheduling() -> None:
    executor = _ControlledExecutor()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=_session()),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda _context: _public(
            PublicState.AUTHENTICATED_REACHABLE,
            BoundaryState.VIOLATION,
        ),
        executor=executor,
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)
    executor.run(0)
    assert provider.snapshot().boundary is BoundaryState.VIOLATION

    provider.request_refresh(full=False)
    provider.request_refresh(full=False)
    executor.run(2)

    overlapped = provider.snapshot()
    assert overlapped.public is PublicState.UNKNOWN
    assert overlapped.boundary is BoundaryState.UNKNOWN
    assert overlapped.public_checked_at is None


def test_freshness_uses_monotonic_elapsed_time_not_wall_clock() -> None:
    clock = _Clock()
    provider = PublicConnectivityProvider(
        context_loader=lambda full: _context(full, session=_session()),
        cloudflared_probe=lambda _expectation: _cloud(
            ownership=OwnershipState.MANAGED,
            service=ServiceState.RUNNING,
        ),
        public_endpoint_probe=lambda _context: _public(PublicState.AUTHENTICATED_REACHABLE),
        executor=_InlineExecutor(),
        utcnow=clock.utcnow,
        monotonic=clock.monotonic,
        max_age_seconds=60,
    )

    provider.request_refresh(full=True)
    clock.adjust_wall(24 * 60 * 60)

    assert provider.snapshot().freshness is FreshnessState.FRESH

    clock.adjust_wall(-(24 * 60 * 60))
    clock.advance_elapsed(61)

    status = provider.snapshot()
    assert status.freshness is FreshnessState.STALE
    assert status.overall is OverallState.UNKNOWN


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
        mobile_endpoint_state: str | None = None,
    ) -> None:
        self.health_state = health_state
        self.healthy = healthy
        self.public_origin = public_origin
        self.mobile_endpoint_state = mobile_endpoint_state or (
            "public_configured_unverified"
            if public_origin is not None
            else ("local_only" if healthy else "unknown")
        )

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
            mobile_endpoint_state=self.mobile_endpoint_state,
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
        assert public_contexts == []
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


def test_builder_blocks_predecessor_auth_while_completed_recovery_is_unsettled() -> None:
    runtime_provider = _RuntimeProvider(_config(), _Runtime(public_origin="https://public.example"))
    public_contexts: list[PublicEndpointContext] = []
    provider = build_public_connectivity_provider(
        runtime_provider,  # type: ignore[arg-type]
        product_session_loader=lambda _installation_id: _session(),
        product_recovery_loader=lambda _installation_id: _completed_recovery(),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda context: (
            public_contexts.append(context),
            _public(
                PublicState.AUTHENTICATED_REACHABLE
                if context.session is not None
                else PublicState.REACHABLE_UNVERIFIED
            ),
        )[-1],
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)

    assert len(public_contexts) == 1
    assert public_contexts[0].session is None
    assert provider.snapshot().public is PublicState.REACHABLE_UNVERIFIED


def test_builder_accepts_promoted_session_matching_completed_recovery() -> None:
    runtime_provider = _RuntimeProvider(_config(), _Runtime(public_origin="https://public.example"))
    promoted = _session(_RECOVERY_SESSION_TOKEN)
    public_contexts: list[PublicEndpointContext] = []
    provider = build_public_connectivity_provider(
        runtime_provider,  # type: ignore[arg-type]
        product_session_loader=lambda _installation_id: promoted,
        product_recovery_loader=lambda _installation_id: _completed_recovery(),
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda context: (
            public_contexts.append(context),
            _public(PublicState.AUTHENTICATED_REACHABLE),
        )[-1],
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=True)

    assert len(public_contexts) == 1
    assert public_contexts[0].session == promoted
    assert provider.snapshot().public is PublicState.AUTHENTICATED_REACHABLE


def test_builder_does_not_report_unconfigured_when_backend_authority_is_unavailable() -> None:
    runtime_provider = _RuntimeProvider(
        _config(public_origin=None),
        _Runtime(health_state="pending", healthy=False, public_origin=None),
    )
    provider = build_public_connectivity_provider(
        runtime_provider,  # type: ignore[arg-type]
        cloudflared_probe=lambda _expectation: _cloud(),
        public_endpoint_probe=lambda _context: _public(),
        executor=_InlineExecutor(),
        utcnow=_Clock().utcnow,
    )

    provider.request_refresh(full=False)

    assert provider.snapshot().public is PublicState.UNKNOWN
