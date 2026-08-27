"""Bounded loopback health transport and installed-backend identity proof."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal

from backend_manager.version_contract import is_managed_release_version

_ATTESTATION_CONTEXT = b"ticketbox/installation-health/v1\0"
_HEX_256 = re.compile(r"[0-9a-f]{64}\Z")
_HEALTH_RESPONSE_LIMIT_BYTES = 4096
_HEALTH_KEYS = frozenset(
    {
        "contract",
        "status",
        "product",
        "backend_version",
        "installation_id",
        "runtime_access_state",
        "owner_state",
        "owner_recovery_channel",
        "mobile_connectivity",
    },
)
_MOBILE_CONNECTIVITY_KEYS = frozenset(
    {"mobile_endpoint_state", "android_binding_state", "iphone_upload_state"},
)
_MOBILE_ENDPOINT_STATES = frozenset({"local_only", "public_configured_unverified"})
_MOBILE_TASK_STATES = frozenset({"setup_required", "configured_unverified"})
_OWNER_STATES = frozenset({"configured", "recovery_required"})
_OWNER_RECOVERY_CHANNELS = frozenset({"development", "managed_host", "operator"})
_RUNTIME_ACCESS_STATES = frozenset({"available", "repair_required"})


@dataclass(frozen=True)
class SourceHealthExpectation:
    installation_id: str
    backend_version: str | None


@dataclass(frozen=True)
class InstalledHealthExpectation:
    installation_id: str
    backend_version: str
    attestation_key: str


HealthExpectation = SourceHealthExpectation | InstalledHealthExpectation


@dataclass(frozen=True)
class HealthProbeResult:
    state: Literal["healthy", "pending", "mismatch", "stopped"]
    detail: str
    mobile_endpoint_state: str = "unknown"
    android_binding_state: str = "unknown"
    iphone_upload_state: str = "unknown"
    runtime_access_state: str = "unknown"
    owner_state: str = "unknown"
    owner_recovery_channel: str = "unknown"

    @property
    def healthy(self) -> bool:
        return self.state == "healthy"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def _sign_challenge(key: str, challenge: str) -> str:
    if _HEX_256.fullmatch(key) is None or _HEX_256.fullmatch(challenge) is None:
        raise ValueError("health attestation input is invalid")
    return hmac.new(
        bytes.fromhex(key),
        _ATTESTATION_CONTEXT + challenge.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _validate_health_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/api/health/installation"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("健康检查 URL 不符合固定 loopback 身份契约。")
    if parsed.port is None:
        raise ValueError("健康检查 URL 缺少端口。")


def _attestation_matches(
    candidate: str | None,
    expectation: HealthExpectation,
    challenge: str,
) -> bool:
    if isinstance(expectation, SourceHealthExpectation):
        return candidate is None
    try:
        expected = _sign_challenge(expectation.attestation_key, challenge)
    except ValueError:
        return False
    return isinstance(candidate, str) and hmac.compare_digest(expected, candidate)


def _mobile_states(candidate: object) -> tuple[str, str, str] | None:
    if not isinstance(candidate, dict) or set(candidate) != _MOBILE_CONNECTIVITY_KEYS:
        return None
    endpoint = candidate.get("mobile_endpoint_state")
    android = candidate.get("android_binding_state")
    iphone = candidate.get("iphone_upload_state")
    if not all(isinstance(value, str) for value in (endpoint, android, iphone)):
        return None
    if (
        endpoint not in _MOBILE_ENDPOINT_STATES
        or android not in _MOBILE_TASK_STATES
        or iphone not in _MOBILE_TASK_STATES
        or (endpoint == "local_only" and (android != "setup_required" or iphone != "setup_required"))
        or (
            endpoint == "public_configured_unverified"
            and (android != "configured_unverified" or iphone != "configured_unverified")
        )
    ):
        return None
    return endpoint, android, iphone


def _parse_health_payload(
    raw: bytes,
    expectation: HealthExpectation,
    *,
    challenge: str,
    attestation: str | None,
) -> HealthProbeResult:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return HealthProbeResult("mismatch", "loopback 响应不是有效的 Ticketbox JSON。")
    if not isinstance(decoded, dict) or set(decoded) != _HEALTH_KEYS:
        return HealthProbeResult("mismatch", "loopback JSON 不符合 Ticketbox 身份字段契约。")
    if not _attestation_matches(attestation, expectation, challenge):
        return HealthProbeResult("mismatch", "loopback 响应不是本机绑定的 Ticketbox 后端。")
    if decoded.get("status") != "ok" or decoded.get("product") != "ticketbox":
        return HealthProbeResult("mismatch", "loopback 服务不是 Ticketbox 后端。")
    if decoded.get("contract") != "ticketbox-installation-health-v2":
        return HealthProbeResult("mismatch", "Ticketbox 安装健康合同版本不匹配。")
    version = decoded.get("backend_version")
    installation_id = decoded.get("installation_id")
    if not is_managed_release_version(version):
        return HealthProbeResult("mismatch", "Ticketbox 后端版本身份无效。")
    if not isinstance(installation_id, str):
        return HealthProbeResult("mismatch", "Ticketbox 安装身份无效。")
    if expectation.backend_version is not None and version != expectation.backend_version:
        return HealthProbeResult("mismatch", "运行中的 Ticketbox 版本与安装记录不一致。")
    if installation_id != expectation.installation_id:
        return HealthProbeResult("mismatch", "运行中的 Ticketbox 实例与本机安装记录不一致。")
    runtime_access_state = decoded.get("runtime_access_state")
    if runtime_access_state not in _RUNTIME_ACCESS_STATES:
        return HealthProbeResult("mismatch", "Ticketbox 运行访问字段合同无效。")
    owner_state = decoded.get("owner_state")
    owner_recovery_channel = decoded.get("owner_recovery_channel")
    if owner_state not in _OWNER_STATES or owner_recovery_channel not in _OWNER_RECOVERY_CHANNELS:
        return HealthProbeResult("mismatch", "Ticketbox 拥有者恢复字段合同无效。")
    mobile_states = _mobile_states(decoded.get("mobile_connectivity"))
    if mobile_states is None:
        return HealthProbeResult("mismatch", "Ticketbox 移动端能力字段合同无效。")
    endpoint_state, android_state, iphone_state = mobile_states
    if runtime_access_state == "repair_required":
        detail = "Ticketbox 后端身份已验证，但安装维护尚未完成。"
    elif owner_state == "recovery_required":
        detail = "Ticketbox 后端身份已验证，但缺少可用拥有者身份。"
    else:
        detail = "Ticketbox 产品、版本、安装身份和拥有者身份已验证。"
    return HealthProbeResult(
        "healthy",
        detail,
        mobile_endpoint_state=endpoint_state,
        android_binding_state=android_state,
        iphone_upload_state=iphone_state,
        runtime_access_state=runtime_access_state,
        owner_state=owner_state,
        owner_recovery_channel=owner_recovery_channel,
    )


def probe_ticketbox_health(
    url: str,
    *,
    expectation: HealthExpectation,
    timeout: float,
) -> HealthProbeResult:
    try:
        _validate_health_url(url)
    except ValueError as exc:
        return HealthProbeResult("mismatch", str(exc))
    challenge = secrets.token_hex(32)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Host": "127.0.0.1",
            "X-Ticketbox-Health-Challenge": challenge,
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310 - validated fixed loopback URL
            if response.status != 200:
                return HealthProbeResult("pending", f"Ticketbox 后端尚未就绪（HTTP {response.status}）。")
            media_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
            if media_type != "application/json":
                return HealthProbeResult("mismatch", "loopback 200 响应不是 Ticketbox JSON。")
            raw = response.read(_HEALTH_RESPONSE_LIMIT_BYTES + 1)
            attestation = response.headers.get("X-Ticketbox-Health-Attestation")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return HealthProbeResult("pending", f"Ticketbox 后端身份检查等待中（{type(exc).__name__}）。")
    if len(raw) > _HEALTH_RESPONSE_LIMIT_BYTES:
        return HealthProbeResult("mismatch", "loopback 健康响应超过 Ticketbox 上限。")
    return _parse_health_payload(
        raw,
        expectation,
        challenge=challenge,
        attestation=attestation,
    )


def health_ok(
    url: str,
    *,
    expectation: HealthExpectation,
    timeout: float,
) -> bool:
    return probe_ticketbox_health(url, expectation=expectation, timeout=timeout).healthy
