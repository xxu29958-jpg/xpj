"""Typed, privacy-safe contracts shared by cloudflared read-only adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from backend_manager.public_connectivity import ConnectorState, OwnershipState, ServiceState


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
