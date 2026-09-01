"""Pure read model for the Desktop Public Connectivity Backstage.

This module owns policy derivation and the stable, privacy-safe projection. It
contains no filesystem, registry, SCM, credential, process, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final


class OwnershipState(StrEnum):
    UNCONFIGURED = "unconfigured"
    EXTERNAL_UNMANAGED = "external_unmanaged"
    MANAGED = "managed"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ServiceState(StrEnum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    STOPPED = "stopped"
    START_PENDING = "start_pending"
    RUNNING = "running"
    STOP_PENDING = "stop_pending"
    FAILED = "failed"
    IDENTITY_MISMATCH = "identity_mismatch"


class ConnectorState(StrEnum):
    UNKNOWN = "unknown"
    CONNECTING = "connecting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    TUNNEL_MISMATCH = "tunnel_mismatch"


class OriginState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNREACHABLE = "unreachable"
    IDENTITY_MISMATCH = "identity_mismatch"


class PublicState(StrEnum):
    UNCONFIGURED = "unconfigured"
    UNKNOWN = "unknown"
    REACHABLE_UNVERIFIED = "reachable_unverified"
    AUTHENTICATED_REACHABLE = "authenticated_reachable"
    UNREACHABLE = "unreachable"
    WRONG_PRODUCT = "wrong_product"


class BoundaryState(StrEnum):
    UNKNOWN = "unknown"
    SAFE = "safe"
    VIOLATION = "violation"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


class ActionState(StrEnum):
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"
    AWAITING_UAC = "awaiting_uac"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN_OUTCOME = "unknown_outcome"
    MANUAL_INTERVENTION = "manual_intervention"


class OverallState(StrEnum):
    UNSAFE = "unsafe"
    OFFLINE = "offline"
    CONNECTOR_UNAVAILABLE = "connector_unavailable"
    ORIGIN_UNAVAILABLE = "origin_unavailable"
    PUBLIC_UNAVAILABLE = "public_unavailable"
    DEGRADED = "degraded"
    HEALTHY = "healthy"
    UNKNOWN = "unknown"


SUPPORTED_READONLY_ACTIONS: Final = (
    "refresh",
    "full_check",
    "export_diagnostics",
)

_STATE_TEXT: Final[dict[StrEnum, str]] = {
    OwnershipState.UNCONFIGURED: "未配置",
    OwnershipState.EXTERNAL_UNMANAGED: "发现外部连接，未由小票夹管理",
    OwnershipState.MANAGED: "由小票夹管理",
    OwnershipState.CONFLICT: "身份冲突",
    OwnershipState.UNKNOWN: "未知",
    ServiceState.UNKNOWN: "未知",
    ServiceState.MISSING: "未安装",
    ServiceState.STOPPED: "已停止",
    ServiceState.START_PENDING: "正在启动",
    ServiceState.RUNNING: "正在运行",
    ServiceState.STOP_PENDING: "正在停止",
    ServiceState.FAILED: "运行失败",
    ServiceState.IDENTITY_MISMATCH: "服务身份不匹配",
    ConnectorState.UNKNOWN: "未知",
    ConnectorState.CONNECTING: "正在连接 Edge",
    ConnectorState.HEALTHY: "Edge 连接正常",
    ConnectorState.DEGRADED: "Edge 连接降级",
    ConnectorState.DOWN: "Edge 未连接",
    ConnectorState.TUNNEL_MISMATCH: "Tunnel 身份不匹配",
    OriginState.UNKNOWN: "未知",
    OriginState.HEALTHY: "小票夹源站正常",
    OriginState.UNREACHABLE: "小票夹源站不可达",
    OriginState.IDENTITY_MISMATCH: "源站身份不匹配",
    PublicState.UNCONFIGURED: "未配置公网地址",
    PublicState.UNKNOWN: "未知",
    PublicState.REACHABLE_UNVERIFIED: "公网可达，尚未用桌面身份验证",
    PublicState.AUTHENTICATED_REACHABLE: "公网产品身份已验证",
    PublicState.UNREACHABLE: "公网端点不可达",
    PublicState.WRONG_PRODUCT: "公网端点不是当前小票夹产品",
    BoundaryState.UNKNOWN: "尚未完整检查",
    BoundaryState.SAFE: "公开边界符合预期",
    BoundaryState.VIOLATION: "发现不应公开的入口",
}

_SUMMARY: Final[dict[str, tuple[str, str]]] = {
    "public_boundary_violation": (
        "公网边界存在风险",
        "停止把该公网入口视为安全，并由维护者检查公开路由边界。",
    ),
    "connector_identity_conflict": (
        "连接器身份存在冲突",
        "当前只保留只读观察；不要对该连接器执行小票夹管理动作。",
    ),
    "service_identity_conflict": (
        "Windows 服务身份不匹配",
        "当前只保留只读观察；由生命周期维护流程核对服务绑定。",
    ),
    "public_connectivity_stale": (
        "公网连接状态已过期",
        "刷新本机状态，或运行一次完整公网检查。",
    ),
    "public_connectivity_unconfigured": (
        "尚未配置小票夹公网连接",
        "本阶段不会创建连接；配置仍由后续受管连接流程负责。",
    ),
    "external_connector_unmanaged": (
        "已发现外部 Cloudflare 连接",
        "该连接不属于小票夹受管对象；这里只显示只读观察。",
    ),
    "cloudflared_service_missing": (
        "受管连接服务不存在",
        "本阶段不会安装服务；由后续生命周期流程处理。",
    ),
    "cloudflared_service_stopped": (
        "受管连接服务已停止",
        "本阶段不会启动服务；由后续生命周期流程处理。",
    ),
    "cloudflared_service_failed": (
        "受管连接服务运行失败",
        "导出安全诊断，并由后续生命周期流程处理。",
    ),
    "cloudflared_start_pending": (
        "连接服务正在启动",
        "稍后刷新状态。",
    ),
    "cloudflared_stop_pending": (
        "连接服务正在停止",
        "稍后刷新状态。",
    ),
    "cloudflared_connecting": (
        "连接器正在连接 Cloudflare Edge",
        "稍后刷新状态。",
    ),
    "cloudflared_degraded": (
        "Cloudflare Edge 连接已降级",
        "运行完整公网检查，并导出安全诊断。",
    ),
    "cloudflared_down": (
        "Cloudflare Edge 当前不可用",
        "检查网络后刷新；本阶段不会重启连接器。",
    ),
    "cloudflared_tunnel_mismatch": (
        "Tunnel 身份与受保护绑定不一致",
        "停止信任该连接器，并由生命周期维护流程核对绑定。",
    ),
    "ticketbox_origin_unreachable": (
        "小票夹本机源站不可达",
        "先恢复小票夹后端，再运行完整公网检查。",
    ),
    "ticketbox_origin_identity_mismatch": (
        "本机源站不是当前小票夹安装",
        "停止信任当前源站，并使用既有安装恢复流程。",
    ),
    "public_endpoint_unreachable": (
        "公网端点不可达",
        "检查网络和公开路由后运行完整公网检查。",
    ),
    "public_endpoint_wrong_product": (
        "公网端点不是当前小票夹产品",
        "停止使用该公网入口并核对远端路由。",
    ),
    "public_reachable_unverified": (
        "公网端点可达但尚未完成产品验证",
        "使用已绑定的 Desktop 身份运行完整公网检查。",
    ),
    "public_connectivity_degraded": (
        "公网连接证据不完整或已降级",
        "运行完整公网检查，并根据各层状态定位问题。",
    ),
    "public_connectivity_healthy": (
        "公网连接已验证可用",
        "无需操作；状态过期后可重新检查。",
    ),
    "public_connectivity_unknown": (
        "公网连接状态未知",
        "刷新本机状态，必要时运行完整公网检查。",
    ),
}
PUBLIC_CONNECTIVITY_STATUS_CODES: Final = frozenset(_SUMMARY)

_OWNERSHIP_CODES: Final = {
    OwnershipState.UNCONFIGURED: "public_connectivity_unconfigured",
    OwnershipState.EXTERNAL_UNMANAGED: "external_connector_unmanaged",
    OwnershipState.UNKNOWN: "public_connectivity_unknown",
}
_SERVICE_CODES: Final = {
    ServiceState.MISSING: "cloudflared_service_missing",
    ServiceState.STOPPED: "cloudflared_service_stopped",
    ServiceState.FAILED: "cloudflared_service_failed",
    ServiceState.START_PENDING: "cloudflared_start_pending",
    ServiceState.STOP_PENDING: "cloudflared_stop_pending",
}
_CONNECTOR_CODES: Final = {
    ConnectorState.CONNECTING: "cloudflared_connecting",
    ConnectorState.DEGRADED: "cloudflared_degraded",
    ConnectorState.DOWN: "cloudflared_down",
    ConnectorState.TUNNEL_MISMATCH: "cloudflared_tunnel_mismatch",
}
_ORIGIN_CODES: Final = {
    OriginState.UNREACHABLE: "ticketbox_origin_unreachable",
    OriginState.IDENTITY_MISMATCH: "ticketbox_origin_identity_mismatch",
}
_PUBLIC_CODES: Final = {
    PublicState.UNREACHABLE: "public_endpoint_unreachable",
    PublicState.WRONG_PRODUCT: "public_endpoint_wrong_product",
    PublicState.REACHABLE_UNVERIFIED: "public_reachable_unverified",
}
_OVERALL_CODES: Final = {
    OverallState.DEGRADED: "public_connectivity_degraded",
    OverallState.HEALTHY: "public_connectivity_healthy",
    OverallState.UNKNOWN: "public_connectivity_unknown",
}


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("public connectivity timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class PublicConnectivityStatus:
    observed_at: datetime | None
    public_checked_at: datetime | None
    ownership: OwnershipState
    service: ServiceState
    connector: ConnectorState
    origin: OriginState
    public: PublicState
    boundary: BoundaryState
    freshness: FreshnessState
    managed_action: ActionState
    cloudflared_version: str | None = None
    connection_count: int | None = None
    service_identity_match: bool | None = None
    binary_identity_match: bool | None = None
    tunnel_identity_match: bool | None = None
    in_progress: bool = False

    @property
    def overall(self) -> OverallState:
        if self.boundary is BoundaryState.VIOLATION or self.ownership is OwnershipState.CONFLICT:
            return OverallState.UNSAFE
        if self.service is ServiceState.IDENTITY_MISMATCH:
            return OverallState.UNSAFE
        if self.freshness is FreshnessState.STALE:
            return OverallState.UNKNOWN
        if self.ownership is not OwnershipState.MANAGED:
            return OverallState.UNKNOWN
        if self.service in {ServiceState.MISSING, ServiceState.STOPPED, ServiceState.FAILED}:
            return OverallState.OFFLINE
        if self.connector in {ConnectorState.DOWN, ConnectorState.TUNNEL_MISMATCH}:
            return OverallState.CONNECTOR_UNAVAILABLE
        if self.origin in {OriginState.UNREACHABLE, OriginState.IDENTITY_MISMATCH}:
            return OverallState.ORIGIN_UNAVAILABLE
        if self.public in {PublicState.UNREACHABLE, PublicState.WRONG_PRODUCT}:
            return OverallState.PUBLIC_UNAVAILABLE
        if (
            self.service in {ServiceState.START_PENDING, ServiceState.STOP_PENDING}
            or self.connector in {ConnectorState.CONNECTING, ConnectorState.DEGRADED}
            or self.public is PublicState.REACHABLE_UNVERIFIED
        ):
            return OverallState.DEGRADED
        if (
            self.service is ServiceState.RUNNING
            and self.connector is ConnectorState.HEALTHY
            and self.origin is OriginState.HEALTHY
            and self.public is PublicState.AUTHENTICATED_REACHABLE
            and self.boundary is BoundaryState.SAFE
        ):
            return OverallState.HEALTHY
        return OverallState.UNKNOWN

    @property
    def code(self) -> str:
        if self.boundary is BoundaryState.VIOLATION:
            return "public_boundary_violation"
        if self.ownership is OwnershipState.CONFLICT:
            return "connector_identity_conflict"
        if self.service is ServiceState.IDENTITY_MISMATCH:
            return "service_identity_conflict"
        if self.freshness is FreshnessState.STALE:
            return "public_connectivity_stale"
        axis_code = (
            _OWNERSHIP_CODES.get(self.ownership)
            or _SERVICE_CODES.get(self.service)
            or _CONNECTOR_CODES.get(self.connector)
            or _ORIGIN_CODES.get(self.origin)
            or _PUBLIC_CODES.get(self.public)
        )
        return axis_code or _OVERALL_CODES.get(self.overall, "public_connectivity_unknown")

    @property
    def summary(self) -> str:
        return _SUMMARY[self.code][0]

    @property
    def next_step(self) -> str:
        return _SUMMARY[self.code][1]

    def current(self, *, now: datetime, max_age: timedelta) -> PublicConnectivityStatus:
        if max_age < timedelta(0):
            raise ValueError("public connectivity max age must not be negative")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("public connectivity current time must be timezone-aware")
        observed = self.observed_at
        stale = observed is None
        if observed is not None:
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError("public connectivity observation must be timezone-aware")
            stale = now.astimezone(UTC) - observed.astimezone(UTC) > max_age
        return replace(
            self,
            freshness=FreshnessState.STALE if stale else FreshnessState.FRESH,
        )

    def _detail_rows(self) -> list[dict[str, str]]:
        observed = _utc_text(self.observed_at)
        version = self.cloudflared_version or "未知"
        return [
            {"label": "小票夹后端", "state": self.overall.value, "text": self.summary},
            {"label": "Windows 服务", "state": self.service.value, "text": _STATE_TEXT[self.service]},
            {"label": "Cloudflare Edge", "state": self.connector.value, "text": _STATE_TEXT[self.connector]},
            {"label": "本机源站", "state": self.origin.value, "text": _STATE_TEXT[self.origin]},
            {"label": "公网端点", "state": self.public.value, "text": _STATE_TEXT[self.public]},
            {"label": "公开边界", "state": self.boundary.value, "text": _STATE_TEXT[self.boundary]},
            {"label": "最近观察", "state": self.freshness.value, "text": observed or "尚无观察"},
            {"label": "cloudflared 版本", "state": "informational", "text": version},
            {"label": "所有权", "state": self.ownership.value, "text": _STATE_TEXT[self.ownership]},
        ]

    def to_projection(self) -> dict[str, object]:
        return {
            "schema": "ticketbox-public-connectivity-v1",
            "overall": self.overall.value,
            "code": self.code,
            "summary": self.summary,
            "next_step": self.next_step,
            "ownership": self.ownership.value,
            "service": self.service.value,
            "connector": self.connector.value,
            "origin": self.origin.value,
            "public": self.public.value,
            "boundary": self.boundary.value,
            "freshness": self.freshness.value,
            "managed_action": self.managed_action.value,
            "observed_at": _utc_text(self.observed_at),
            "public_checked_at": _utc_text(self.public_checked_at),
            "in_progress": self.in_progress,
            "cloudflared_version": self.cloudflared_version,
            "connection_count": self.connection_count,
            "service_identity_match": self.service_identity_match,
            "binary_identity_match": self.binary_identity_match,
            "tunnel_identity_match": self.tunnel_identity_match,
            "supported_actions": list(SUPPORTED_READONLY_ACTIONS),
            "detail_rows": self._detail_rows(),
        }


def unknown_public_connectivity_status() -> PublicConnectivityStatus:
    return PublicConnectivityStatus(
        observed_at=None,
        public_checked_at=None,
        ownership=OwnershipState.UNKNOWN,
        service=ServiceState.UNKNOWN,
        connector=ConnectorState.UNKNOWN,
        origin=OriginState.UNKNOWN,
        public=PublicState.UNKNOWN,
        boundary=BoundaryState.UNKNOWN,
        freshness=FreshnessState.STALE,
        managed_action=ActionState.UNAVAILABLE,
    )
