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

from fastapi import Request

from app.config import get_settings
from app.errors import AppError


# Loopback peer addresses we trust. Anything else is rejected outright.
_LOOPBACK_PEERS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Host headers that identify a request as coming from the local machine. The
# port may be omitted, the default backend port (8000), or any of the
# loopback aliases. Anything else (including the public Cloudflare Tunnel
# hostname) is treated as "public" and may be rejected by callers.
_LOOPBACK_HOSTS: frozenset[str] = frozenset(
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


def _peer_host(request: Request) -> str:
    return request.client.host if request.client else ""


def _request_host(request: Request) -> str:
    return (request.headers.get("host") or "").strip().lower()


def is_loopback_request(request: Request) -> bool:
    """Return ``True`` only when both the TCP peer and the Host header look
    like a local-machine request."""
    return _peer_host(request) in _LOOPBACK_PEERS and _request_host(request) in _LOOPBACK_HOSTS


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
        "管理 API 默认仅允许本机访问。",
        status_code=403,
    )
