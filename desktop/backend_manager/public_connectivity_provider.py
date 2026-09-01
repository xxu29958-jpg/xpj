"""Asynchronous composition and cache for public-connectivity evidence."""

from __future__ import annotations

import secrets
import threading
import time
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
from backend_manager.product_data import ProductDataError, derive_desktop_pending_token
from backend_manager.product_identity import (
    ProductCredentialError,
    ProductSession,
    load_product_session,
)
from backend_manager.product_recovery import RebindRecovery, load_rebind_recovery
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
    public_origin_configured: bool | None
    session: ProductSession | None = field(default=None, repr=False)
    connector_expectation: ManagedConnectorExpectation | None = field(default=None, repr=False)


class _StopEvent(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


class PublicConnectivityReader(Protocol):
    """Cache-only surface consumed by the synchronous Manager controller."""

    def snapshot(self) -> PublicConnectivityStatus: ...

    def request_refresh(self, *, full: bool = False) -> int: ...

    def invalidate_product_session(self) -> None: ...

    def begin_product_session_mutation(self) -> None: ...

    def end_product_session_mutation(self) -> None: ...


class CacheOnlyUnknownPublicConnectivityProvider:
    """No-I/O fallback for callers that do not own a probe lifetime."""

    def snapshot(self) -> PublicConnectivityStatus:
        return unknown_public_connectivity_status()

    def request_refresh(self, *, full: bool = False) -> int:
        return 0

    def invalidate_product_session(self) -> None:
        return None

    def begin_product_session_mutation(self) -> None:
        return None

    def end_product_session_mutation(self) -> None:
        return None


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
        monotonic: Callable[[], float] = time.monotonic,
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
        self._monotonic = monotonic
        self._refresh_interval_seconds = refresh_interval_seconds
        self._max_age = timedelta(seconds=max_age_seconds)
        self._lock = threading.RLock()
        self._status = unknown_public_connectivity_status()
        self._last_public_result: PublicEndpointProbeResult | None = None
        self._last_public_origin: str | None = None
        self._last_public_origin_configured: bool | None = None
        self._last_public_checked_at: datetime | None = None
        self._last_public_checked_monotonic: float | None = None
        self._status_observed_monotonic: float | None = None
        self._requested_generation = 0
        self._product_session_mutation_depth = 0
        self._futures: set[Future] = set()
        self._shutdown = False

    def snapshot(self) -> PublicConnectivityStatus:
        with self._lock:
            cached = self._status
            observed_monotonic = self._status_observed_monotonic
        current_monotonic = self._monotonic()
        evidence_age = None
        if observed_monotonic is not None:
            evidence_age = timedelta(seconds=max(0.0, current_monotonic - observed_monotonic))
        return cached.current(evidence_age=evidence_age, max_age=self._max_age)

    def invalidate_product_session(self) -> None:
        """Retire evidence authenticated by a superseded Desktop session."""

        with self._lock:
            if self._shutdown:
                return
            self._retire_product_session_evidence_locked()

    def begin_product_session_mutation(self) -> None:
        """Open a fail-closed window around Backend/WinCred session changes."""

        with self._lock:
            if self._shutdown:
                return
            self._product_session_mutation_depth += 1
            self._retire_product_session_evidence_locked()

    def end_product_session_mutation(self) -> None:
        with self._lock:
            if self._product_session_mutation_depth == 0:
                return
            self._product_session_mutation_depth -= 1
            if not self._shutdown:
                # Bar any check that started inside the mutation window, even
                # when the remote commit or local persistence reported failure.
                self._retire_product_session_evidence_locked()

    def _retire_product_session_evidence_locked(self) -> None:
        # The generation bump bars a running check that captured a bearer whose
        # Backend or WinCred truth is changing from publishing afterward.
        self._requested_generation += 1
        self._clear_cached_public_evidence_locked()
        self._status = replace(
            self._status,
            observed_at=None,
            public_checked_at=None,
            public=PublicState.UNKNOWN,
            boundary=BoundaryState.UNKNOWN,
            freshness=FreshnessState.STALE,
            in_progress=False,
        )
        self._status_observed_monotonic = None

    def _clear_cached_public_evidence_locked(self) -> None:
        self._last_public_result = None
        self._last_public_origin = None
        self._last_public_origin_configured = None
        self._last_public_checked_at = None
        self._last_public_checked_monotonic = None

    def request_refresh(self, *, full: bool = False) -> int:
        with self._lock:
            if self._shutdown:
                raise PublicConnectivityProviderClosedError("public connectivity provider is closed")
            if self._product_session_mutation_depth:
                # The coordinator is between Backend and WinCred truth. Keep
                # the public surface neutral and do not let a probe choose one
                # side of that transition as the new authenticated subject.
                self._requested_generation += 1
                return self._requested_generation
            overlap = self._status.in_progress
            if overlap:
                # A newer request can supersede an older worker between its
                # authority observation and invalidation lock. Retire all
                # reusable public evidence before that newer work is visible.
                self._clear_cached_public_evidence_locked()
            self._requested_generation += 1
            generation = self._requested_generation
            self._status = replace(self._status, in_progress=True)
        try:
            future = self._executor.submit(self._refresh_worker, generation, full)
        except Exception:
            with self._lock:
                if generation == self._requested_generation:
                    if overlap:
                        self._status = unknown_public_connectivity_status()
                        self._status_observed_monotonic = None
                    else:
                        self._status = replace(self._status, in_progress=False)
            raise PublicConnectivityProviderClosedError("public connectivity provider rejected work") from None
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._forget_future)
        return generation

    def run_monitor(self, stop_event: _StopEvent) -> None:
        while not stop_event.wait(self._refresh_interval_seconds):
            with self._lock:
                should_refresh = (
                    not self._shutdown
                    and not self._status.in_progress
                    and self._product_session_mutation_depth == 0
                )
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
        observed_monotonic = self._monotonic()
        endpoint_result: PublicEndpointProbeResult | None = None
        public_checked_at: datetime | None = None
        public_checked_monotonic: float | None = None
        public_origin: str | None = None
        public_origin_configured: bool | None = None
        cache_origin_mismatch = False
        refresh_failed = False
        try:
            context = self._context_loader(full)
            public_origin = context.public_origin
            public_origin_configured = context.public_origin_configured
            # Authority loss must retire the old subject before any slower
            # probe can let a newer generation reuse pre-loss evidence.
            with self._lock:
                if generation == self._requested_generation and (
                    self._last_public_origin != public_origin
                    or self._last_public_origin_configured != public_origin_configured
                ):
                    self._clear_cached_public_evidence_locked()
                    self._last_public_origin = public_origin
                    self._last_public_origin_configured = public_origin_configured
            cloud = self._cloudflared_probe(context.connector_expectation)
            if full and public_origin_configured is True and public_origin is not None:
                endpoint_result = self._public_endpoint_probe(
                    PublicEndpointContext(
                        public_origin=context.public_origin,
                        session=context.session,
                    )
                )
                public_checked_at = now
                public_checked_monotonic = observed_monotonic
            else:
                with self._lock:
                    cache_origin_mismatch = (
                        self._last_public_origin != public_origin
                        or self._last_public_origin_configured != public_origin_configured
                    )
                    if not cache_origin_mismatch:
                        endpoint_result = self._last_public_result
                        public_checked_at = self._last_public_checked_at
                        public_checked_monotonic = self._last_public_checked_monotonic
            assembled = self._assemble(
                now=now,
                context=context,
                cloud=cloud,
                endpoint=endpoint_result,
                public_checked_at=public_checked_at,
            )
            if assembled.observed_at is None:
                status_observed_monotonic = None
            elif endpoint_result is not None:
                status_observed_monotonic = public_checked_monotonic
            else:
                status_observed_monotonic = observed_monotonic
        except Exception:
            refresh_failed = True
            assembled = replace(
                unknown_public_connectivity_status(),
                observed_at=now,
                freshness=FreshnessState.FRESH,
                in_progress=False,
            )
            endpoint_result = None
            public_checked_at = None
            public_checked_monotonic = None
            status_observed_monotonic = observed_monotonic
        with self._lock:
            if generation != self._requested_generation or self._shutdown:
                return
            if full or refresh_failed:
                self._last_public_result = endpoint_result
                self._last_public_origin = public_origin
                self._last_public_origin_configured = public_origin_configured
                self._last_public_checked_at = public_checked_at
                self._last_public_checked_monotonic = public_checked_monotonic
            elif cache_origin_mismatch:
                self._clear_cached_public_evidence_locked()
                self._last_public_origin = public_origin
                self._last_public_origin_configured = public_origin_configured
            self._status = assembled
            self._status_observed_monotonic = status_observed_monotonic

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
        elif context.public_origin_configured is False:
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
    product_recovery_loader: Callable[[str], RebindRecovery | None] = load_rebind_recovery,
    cloudflared_probe: Callable[[ManagedConnectorExpectation | None], CloudflaredProbeResult] = (
        default_cloudflared_probe
    ),
    public_endpoint_probe: Callable[[PublicEndpointContext], PublicEndpointProbeResult] = (
        default_public_endpoint_probe
    ),
    executor: Executor | None = None,
    utcnow: Callable[[], datetime] = _utcnow,
    monotonic: Callable[[], float] = time.monotonic,
    refresh_interval_seconds: float = 10.0,
    max_age_seconds: float = 60.0,
) -> PublicConnectivityProvider:
    """Wire current runtime truth into the independent read-only provider."""

    def load_context(full: bool) -> PublicConnectivityContext:
        projection = runtime_provider.current()
        config = projection.config
        snapshot = projection.runtime.status()
        public_origin = snapshot.public_origin
        public_origin_configured: bool | None = None
        if snapshot.mobile_endpoint_state == "local_only" and public_origin is None:
            public_origin_configured = False
        elif snapshot.mobile_endpoint_state == "public_configured_unverified" and public_origin:
            public_origin_configured = True
        session: ProductSession | None = None
        if full and public_origin_configured is True:
            try:
                session = product_session_loader(config.expected_installation_id)
                recovery = product_recovery_loader(config.expected_installation_id)
                if recovery is not None and recovery.ledger_id:
                    promoted_token = derive_desktop_pending_token(
                        recovery.activation_attempt_secret,
                        recovery.activation_attempt_id,
                    )
                    if session is None or not secrets.compare_digest(
                        session.session_token,
                        promoted_token,
                    ):
                        # A completed recovery record is the durable proof that
                        # Backend and primary WinCred may disagree. Never reuse
                        # the predecessor merely because Backend still accepts
                        # it during rotation grace; reconciliation must first
                        # promote the derived successor into the primary slot.
                        session = None
            except (ProductCredentialError, ProductDataError):
                session = None
        return PublicConnectivityContext(
            origin=_origin_state(snapshot),
            public_origin=public_origin,
            public_origin_configured=public_origin_configured,
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
        monotonic=monotonic,
        refresh_interval_seconds=refresh_interval_seconds,
        max_age_seconds=max_age_seconds,
    )
