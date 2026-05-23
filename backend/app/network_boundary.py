"""Network boundary helpers — v0.3-rc1-preflight.

These helpers harden two privilege boundaries that were previously protected
only by the TCP peer address. Cloudflare Tunnel forwards public requests to
``127.0.0.1``, so the apparent client host is loopback even for traffic that
originated on the open internet. To distinguish those two cases we inspect
the HTTP ``Host`` header in addition to the TCP peer.

We deliberately do **not** trust ``X-Forwarded-For`` / ``CF-Connecting-IP`` /
``X-Real-IP`` here — those headers are attacker-controllable on a publicly
exposed origin. The ``Host`` header is what Cloudflare Tunnel sets to the
public hostname (e.g. ``api.zen70.cn``) and is the only signal we rely on.
"""

from __future__ import annotations

import logging
import os
import re
from ipaddress import ip_address

from fastapi import Request

from app.config import get_settings
from app.errors import AppError

logger = logging.getLogger(__name__)

# Loopback peer addresses we trust. Anything else is rejected outright.
_LOOPBACK_PEERS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Host headers that identify a request as coming from the local machine. The
# port may be omitted, the default backend port (8000), or any of the
# loopback aliases. Anything else (including the public Cloudflare Tunnel
# hostname) is treated as "public" and may be rejected by callers.
_BASE_LOOPBACK_HOSTS: frozenset[str] = frozenset(
    {
        "127.0.0.1",
        "127.0.0.1:8000",
        "localhost",
        "localhost:8000",
        "[::1]",
        "[::1]:8000",
        "::1",
        "::1:8000",
    }
)


# Loopback-style Host header that the extra-allow list may legitimately need.
# Only literal loopback addresses + optional port. Anything resembling a DNS
# name (including the public Cloudflare Tunnel hostname) is rejected — adding
# such a host to XPJ_EXTRA_LOOPBACK_HOSTS would silently widen /web / /owner
# beyond loopback-only.
_LOOPBACK_STYLE_HOST = re.compile(
    r"^(?:127\.0\.0\.1|::1|\[::1\]|localhost)(?::\d+)?$",
    re.IGNORECASE,
)


def _is_loopback_style_host(host: str) -> bool:
    return bool(_LOOPBACK_STYLE_HOST.match(host))


def _extra_loopback_hosts() -> frozenset[str]:
    """Honour the ``XPJ_EXTRA_LOOPBACK_HOSTS`` env var (comma-separated).

    Used by local tooling that runs uvicorn on a non-default port (e.g. the
    screenshot capture script on :8765). Never expand this list at runtime
    based on request headers — only static, owner-controlled config.

    Non-loopback-style entries (anything that doesn't match 127.0.0.1[:port] /
    localhost[:port] / [::1][:port] / ::1[:port]) are dropped with a loud
    log.error — accepting them would let an operator who pastes the public
    Cloudflare Tunnel hostname into this env var silently disable the /web /
    /owner Host-header gate.
    """
    raw = os.environ.get("XPJ_EXTRA_LOOPBACK_HOSTS", "")
    if not raw:
        return frozenset()
    accepted: set[str] = set()
    rejected: list[str] = []
    for item in raw.split(","):
        host = item.strip().lower()
        if not host:
            continue
        if _is_loopback_style_host(host):
            accepted.add(host)
        else:
            rejected.append(host)
    if rejected:
        logger.error(
            "XPJ_EXTRA_LOOPBACK_HOSTS contains non-loopback entries; "
            "ignored: %s. Only 127.0.0.1[:port] / localhost[:port] / "
            "[::1][:port] / ::1[:port] are accepted.",
            rejected,
        )
    return frozenset(accepted)


def _loopback_hosts() -> frozenset[str]:
    return _BASE_LOOPBACK_HOSTS | _extra_loopback_hosts()


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _request_host(request: Request) -> str:
    return (request.headers.get("host") or "").strip().lower()


def is_loopback_request(request: Request) -> bool:
    """Return ``True`` only when both the TCP peer and the Host header look
    like a local-machine request."""
    return _peer_host(request) in _LOOPBACK_PEERS and _request_host(request) in _loopback_hosts()


def pairing_rate_limit_key(request: Request) -> str:
    """Return a rate-limit/audit key, never an authorization signal.

    Public Cloudflare Tunnel requests arrive from a loopback peer with a
    public Host header. In that narrow case, ``CF-Connecting-IP`` can be used
    to avoid collapsing every browser login attempt into ``127.0.0.1``.
    """
    peer = _peer_host(request) or "unknown"
    host = _request_host(request)
    cf_connecting_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if peer in _LOOPBACK_PEERS and host not in _loopback_hosts() and cf_connecting_ip:
        try:
            return f"cf:{ip_address(cf_connecting_ip)}"
        except ValueError:
            pass
    return f"peer:{peer}"


def require_owner_console_local(request: Request) -> None:
    """Owner Console gate. Rejects any request that does not look local on
    both the TCP peer and the HTTP Host header. Public Host headers (e.g.
    forwarded by Cloudflare Tunnel) are blocked unconditionally — Owner
    Console has no public mode."""
    if not is_loopback_request(request):
        raise AppError(
            "invalid_request",
            "Owner Console 仅允许本机访问。",
            status_code=403,
        )


def require_admin_network_boundary(request: Request) -> None:
    """``/api/admin/*`` gate. Loopback requests are always allowed. Public
    Host headers are rejected unless ``ALLOW_PUBLIC_ADMIN_API=true`` is set
    in the environment, in which case the admin token alone protects the
    endpoint."""
    if is_loopback_request(request):
        return
    if get_settings().allow_public_admin_api:
        return
    raise AppError(
        "admin_api_local_only",
        status_code=403,
    )
