"""Asynchronous composition and cache for public-connectivity evidence."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from backend_manager.cloudflared_probe import (
    CloudflaredProbeResult,
    ManagedConnectorExpectation,
)
from backend_manager.cloudflared_probe import probe_cloudflared as default_cloudflared_probe
from backend_manager.product_identity import (
    ProductCredentialError,
    ProductSession,
    load_product_session,
)
from backend_manager.projection import RuntimeConfigProvider
from backend_manager.public_connectivity import (
    ActionState,
    BoundaryState,
    FreshnessState,
    OriginState,
    PublicConnectivityStatus,
    PublicState,
    unknown_public_connectivity_status,
)
from backend_manager.public_endpoint_probe import (
    PublicEndpointContext,
    PublicEndpointProbeResult,
)
from backend_manager.public_endpoint_probe import (
    probe_public_endpoint as default_public_endpoint_probe,
)
from backend_manager.runtime import RuntimeStatus


class PublicConnectivityProviderClosedError(RuntimeError):
    """Raised when an action races with provider shutdown."""


@dataclass(frozen=True)
class PublicConnectivityContext:
    origin: OriginState
    public_origin: str | None
    session: ProductSession | None = field(default=None, repr=False)
    connector_expectation: ManagedConnectorExpectation | None = field(default=None, repr=False)


class _StopEvent(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


class PublicConnectivityReader(Protocol):
    """Cache-only surface consumed by the synchronous Manager controller."""

    def snapshot(self) -> PublicConnectivityStatus: ...

    def request_refresh(self, *, full: bool = False) -> int: ...


class CacheOnlyUnknownPublicConnectivityProvider:
    """No-I/O fallback for callers that do not own a probe lifetime."""

    def snapshot(self) -> PublicConnectivityStatus:
        return unknown_public_connectivity_status()

    def request_refresh(self, *, full: bool = False) -> int:
        return 0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _origin_state(snapshot: RuntimeStatus) -> OriginState:
    if snapshot.health_state == "mismatch":
        return OriginState.IDENTITY_MISMATCH
    if snapshot.healthy and snapshot.health_state == "healthy":
        return OriginState.HEALTHY
    if not snapshot.running or snapshot.health_state in {"stopped", "failed", "unreachable"}:
        return OriginState.UNREACHABLE
    return OriginState.UNKNOWN


class PublicConnectivityProvider:
    """Own scheduling, freshness, and last-writer ordering for read probes."""

    def __init__(
        self,
        *,
        context_loader: Callable[[bool], PublicConnectivityContext],
        cloudflared_probe: Callable[[ManagedConnectorExpectation | None], CloudflaredProbeResult],
        public_endpoint_probe: Callable[[PublicEndpointContext], PublicEndpointProbeResult],
        executor: Executor | None = None,
        utcnow: Callable[[], datetime] = _utcnow,
        refresh_interval_seconds: float = 10.0,
        max_age_seconds: float = 60.0,
    ) -> None:
        if refresh_interval_seconds <= 0 or max_age_seconds <= 0:
            raise ValueError("public connectivity timing must be positive")
        self._context_loader = context_loader
        self._cloudflared_probe = cloudflared_probe
        self._public_endpoint_probe = public_endpoint_probe
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="ticketbox-public-connectivity",
        )
        self._utcnow = utcnow
        self._refresh_interval_seconds = refresh_interval_seconds
        self._max_age = timedelta(seconds=max_age_seconds)
        self._lock = threading.RLock()
        self._status = unknown_public_connectivity_status()
        self._last_public_result: PublicEndpointProbeResult | None = None
        self._last_public_checked_at: datetime | None = None
        self._requested_generation = 0
        self._futures: set[Future] = set()
        self._shutdown = False

    def snapshot(self) -> PublicConnectivityStatus:
        with self._lock:
            cached = self._status
        return cached.current(now=self._utcnow(), max_age=self._max_age)

    def request_refresh(self, *, full: bool = False) -> int:
        with self._lock:
            if self._shutdown:
                raise PublicConnectivityProviderClosedError("public connectivity provider is closed")
            self._requested_generation += 1
            generation = self._requested_generation
            self._status = replace(self._status, in_progress=True)
        try:
            future = self._executor.submit(self._refresh_worker, generation, full)
        except Exception:
            with self._lock:
                if generation == self._requested_generation:
                    self._status = replace(self._status, in_progress=False)
            raise PublicConnectivityProviderClosedError("public connectivity provider rejected work") from None
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget_future)
        return generation

    def run_monitor(self, stop_event: _StopEvent) -> None:
        while not stop_event.wait(self._refresh_interval_seconds):
            with self._lock:
                should_refresh = not self._shutdown and not self._status.in_progress
            if should_refresh:
                try:
                    self.request_refresh(full=False)
                except PublicConnectivityProviderClosedError:
                    return

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            futures = tuple(self._futures)
            self._status = replace(self._status, in_progress=False)
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _forget_future(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def _refresh_worker(self, generation: int, full: bool) -> None:
        now = self._utcnow()
        endpoint_result: PublicEndpointProbeResult | None = None
        public_checked_at: datetime | None = None
        try:
            context = self._context_loader(full)
            cloud = self._cloudflared_probe(context.connector_expectation)
            if full:
                endpoint_result = self._public_endpoint_probe(
                    PublicEndpointContext(
                        public_origin=context.public_origin,
                        session=context.session,
                    )
                )
                public_checked_at = now
            else:
                with self._lock:
                    endpoint_result = self._last_public_result
                    public_checked_at = self._last_public_checked_at
            assembled = self._assemble(
                now=now,
                context=context,
                cloud=cloud,
                endpoint=endpoint_result,
                public_checked_at=public_checked_at,
            )
        except Exception:
            assembled = replace(
                unknown_public_connectivity_status(),
                observed_at=now,
                freshness=FreshnessState.FRESH,
                in_progress=False,
            )
            endpoint_result = None
            public_checked_at = None
        with self._lock:
            if generation != self._requested_generation or self._shutdown:
                return
            if full:
                self._last_public_result = endpoint_result
                self._last_public_checked_at = public_checked_at
            self._status = assembled

    @staticmethod
    def _assemble(
        *,
        now: datetime,
        context: PublicConnectivityContext,
        cloud: CloudflaredProbeResult,
        endpoint: PublicEndpointProbeResult | None,
        public_checked_at: datetime | None,
    ) -> PublicConnectivityStatus:
        if endpoint is not None:
            public = endpoint.public
            boundary = endpoint.boundary
        elif context.public_origin is None:
            public = PublicState.UNCONFIGURED
            boundary = BoundaryState.UNKNOWN
        else:
            public = PublicState.UNKNOWN
            boundary = BoundaryState.UNKNOWN
        if public is PublicState.UNCONFIGURED:
            observed_at = now
        elif public_checked_at is None:
            observed_at = None
        else:
            observed_at = min(now, public_checked_at)
        return PublicConnectivityStatus(
            observed_at=observed_at,
            public_checked_at=public_checked_at,
            ownership=cloud.ownership,
            service=cloud.service,
            connector=cloud.connector,
            origin=context.origin,
            public=public,
            boundary=boundary,
            freshness=FreshnessState.FRESH,
            managed_action=ActionState.UNAVAILABLE,
            cloudflared_version=cloud.cloudflared_version,
            connection_count=cloud.connection_count,
            service_identity_match=cloud.service_identity_match,
            binary_identity_match=cloud.binary_identity_match,
            tunnel_identity_match=cloud.tunnel_identity_match,
            in_progress=False,
        )


def build_public_connectivity_provider(
    runtime_provider: RuntimeConfigProvider,
    *,
    product_session_loader: Callable[[str], ProductSession | None] = load_product_session,
    cloudflared_probe: Callable[[ManagedConnectorExpectation | None], CloudflaredProbeResult] = (
        default_cloudflared_probe
    ),
    public_endpoint_probe: Callable[[PublicEndpointContext], PublicEndpointProbeResult] = (
        default_public_endpoint_probe
    ),
    executor: Executor | None = None,
    utcnow: Callable[[], datetime] = _utcnow,
    refresh_interval_seconds: float = 10.0,
    max_age_seconds: float = 60.0,
) -> PublicConnectivityProvider:
    """Wire current runtime truth into the independent read-only provider."""

    def load_context(full: bool) -> PublicConnectivityContext:
        projection = runtime_provider.current()
        config = projection.config
        snapshot = projection.runtime.status()
        session: ProductSession | None = None
        if full and config.public_base_url:
            try:
                session = product_session_loader(config.expected_installation_id)
            except ProductCredentialError:
                session = None
        return PublicConnectivityContext(
            origin=_origin_state(snapshot),
            public_origin=config.public_base_url,
            session=session,
            # The current installed release has no protected connector
            # projection. Absence is material: external evidence cannot be
            # promoted to managed ownership.
            connector_expectation=None,
        )

    return PublicConnectivityProvider(
        context_loader=load_context,
        cloudflared_probe=cloudflared_probe,
        public_endpoint_probe=public_endpoint_probe,
        executor=executor,
        utcnow=utcnow,
        refresh_interval_seconds=refresh_interval_seconds,
        max_age_seconds=max_age_seconds,
    )
