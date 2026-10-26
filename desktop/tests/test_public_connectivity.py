from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend_manager.public_connectivity import (
    ActionState,
    BoundaryState,
    ConnectorState,
    FreshnessState,
    OriginState,
    OverallState,
    OwnershipState,
    PublicConnectivityStatus,
    PublicState,
    ServiceState,
    unknown_public_connectivity_status,
)

_NOW = datetime(2026, 9, 1, 8, 30, tzinfo=UTC)


def _status(**changes: object) -> PublicConnectivityStatus:
    baseline = PublicConnectivityStatus(
        observed_at=_NOW,
        public_checked_at=_NOW,
        ownership=OwnershipState.MANAGED,
        service=ServiceState.RUNNING,
        connector=ConnectorState.HEALTHY,
        origin=OriginState.HEALTHY,
        public=PublicState.AUTHENTICATED_REACHABLE,
        boundary=BoundaryState.SAFE,
        freshness=FreshnessState.FRESH,
        managed_action=ActionState.UNAVAILABLE,
        cloudflared_version="2026.8.1",
        connection_count=4,
        service_identity_match=True,
        binary_identity_match=True,
        tunnel_identity_match=True,
        in_progress=False,
    )
    return replace(baseline, **changes)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"boundary": BoundaryState.VIOLATION}, OverallState.UNSAFE),
        ({"ownership": OwnershipState.CONFLICT}, OverallState.UNSAFE),
        ({"service": ServiceState.IDENTITY_MISMATCH}, OverallState.UNSAFE),
        ({"service": ServiceState.STOPPED}, OverallState.OFFLINE),
        ({"service": ServiceState.MISSING}, OverallState.OFFLINE),
        ({"connector": ConnectorState.DOWN}, OverallState.CONNECTOR_UNAVAILABLE),
        ({"connector": ConnectorState.TUNNEL_MISMATCH}, OverallState.CONNECTOR_UNAVAILABLE),
        ({"origin": OriginState.UNREACHABLE}, OverallState.ORIGIN_UNAVAILABLE),
        ({"origin": OriginState.IDENTITY_MISMATCH}, OverallState.ORIGIN_UNAVAILABLE),
        ({"public": PublicState.WRONG_PRODUCT}, OverallState.PUBLIC_UNAVAILABLE),
        ({"public": PublicState.UNREACHABLE}, OverallState.PUBLIC_UNAVAILABLE),
        ({"public": PublicState.REACHABLE_UNVERIFIED}, OverallState.DEGRADED),
        ({"connector": ConnectorState.DEGRADED}, OverallState.DEGRADED),
        ({}, OverallState.HEALTHY),
    ],
)
def test_overall_priority(changes: dict[str, object], expected: OverallState) -> None:
    assert _status(**changes).overall is expected


@pytest.mark.parametrize(
    "ownership",
    [
        OwnershipState.UNCONFIGURED,
        OwnershipState.EXTERNAL_UNMANAGED,
        OwnershipState.UNKNOWN,
    ],
)
def test_non_managed_ownership_can_never_be_healthy(ownership: OwnershipState) -> None:
    status = _status(ownership=ownership)

    assert status.overall is OverallState.UNKNOWN
    assert status.code in {
        "public_connectivity_unconfigured",
        "external_connector_unmanaged",
        "public_connectivity_unknown",
    }


def test_installed_setup_keeps_external_handoff_visible_before_managed_configuration() -> None:
    status = _status(
        ownership=OwnershipState.EXTERNAL_UNMANAGED,
        managed_action=ActionState.AVAILABLE,
        configured=False,
        desired_enabled=False,
    )
    projection = status.to_projection()

    assert projection["code"] == "external_connector_unmanaged"
    assert "旧连接仍由原工具管理" in projection["next_step"]
    assert "旧连接已退出该地址的转发" in projection["next_step"]
    assert projection["managed_action"] == "available"
    assert replace(status, ownership=OwnershipState.UNCONFIGURED).code == "connector_setup_available"


def test_stale_healthy_demotes_to_unknown_but_known_violation_remains_unsafe() -> None:
    stale = _status().current(evidence_age=timedelta(seconds=61), max_age=timedelta(seconds=60))
    stale_violation = _status(boundary=BoundaryState.VIOLATION).current(
        evidence_age=timedelta(seconds=61),
        max_age=timedelta(seconds=60),
    )

    assert stale.freshness is FreshnessState.STALE
    assert stale.overall is OverallState.UNKNOWN
    assert stale.code == "public_connectivity_stale"
    assert stale_violation.freshness is FreshnessState.STALE
    assert stale_violation.overall is OverallState.UNSAFE
    assert stale_violation.code == "public_boundary_violation"


def test_current_marks_evidence_at_the_age_boundary_fresh() -> None:
    current = _status().current(
        evidence_age=timedelta(seconds=60),
        max_age=timedelta(seconds=60),
    )

    assert current.freshness is FreshnessState.FRESH
    assert current.overall is OverallState.HEALTHY


@pytest.mark.parametrize("public", [PublicState.AUTHENTICATED_REACHABLE, PublicState.REACHABLE_UNVERIFIED])
def test_paused_local_connection_does_not_claim_shared_public_origin_is_closed(public) -> None:
    status = _status(configured=True, desired_enabled=False, service=ServiceState.STOPPED,
        connector=ConnectorState.DOWN, public=public)

    assert status.code == "connector_paused"
    assert status.summary == "本机已暂停，公网仍可达"
    assert "其他连接" in status.next_step
    assert "Cloudflare" in status.next_step
    assert replace(status, public=PublicState.UNREACHABLE).summary == "本机公网连接已暂停"
    assert replace(status, public=PublicState.UNKNOWN).summary == "本机公网连接已暂停"
    assert replace(status, freshness=FreshnessState.STALE).code == "public_connectivity_stale"
    assert "仍可达" not in replace(status, freshness=FreshnessState.STALE).summary


def test_projection_is_stable_ui_ready_and_contains_only_readonly_actions() -> None:
    projection = _status().to_projection()

    assert projection["schema"] == "ticketbox-public-connectivity-v1"
    assert projection["overall"] == "healthy"
    assert projection["code"] == "public_connectivity_healthy"
    assert projection["summary"] == "公网连接已验证可用"
    assert projection["supported_actions"] == ["refresh", "full_check", "export_diagnostics"]
    assert projection["observed_at"] == "2026-09-01T08:30:00+00:00"
    assert projection["public_checked_at"] == "2026-09-01T08:30:00+00:00"
    assert projection["managed_action"] == "unavailable"
    assert projection["connection_count"] == 4
    rows = {row["label"]: row["text"] for row in projection["detail_rows"]}
    assert rows["Cloudflare Edge"] == "Edge 连接正常"
    assert rows["本机源站"] == "小票夹源站正常"
    assert [row["label"] for row in projection["detail_rows"]] == [
        "小票夹后端",
        "Windows 服务",
        "Cloudflare Edge",
        "本机源站",
        "公网端点",
        "公开边界",
        "最近观察",
        "cloudflared 版本",
        "所有权",
    ]

    forbidden_keys = {
        "public_origin",
        "public_url",
        "tunnel_id",
        "connector_id",
        "image_path",
        "argv",
        "token",
        "authorization",
    }
    assert forbidden_keys.isdisjoint(projection)


def test_unknown_factory_is_fail_closed_and_contains_no_mutation_action() -> None:
    status = unknown_public_connectivity_status()
    projection = status.to_projection()

    assert status.overall is OverallState.UNKNOWN
    assert status.freshness is FreshnessState.STALE
    assert status.managed_action is ActionState.UNAVAILABLE
    assert projection["supported_actions"] == ["refresh", "full_check", "export_diagnostics"]
    serialized = repr(projection).lower()
    for forbidden in ("install", "start_cloudflared", "stop_cloudflared", "restart_cloudflared", "repair"):
        assert forbidden not in serialized
