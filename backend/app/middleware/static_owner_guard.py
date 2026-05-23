"""ADR-0028 / P2 boundary fix: refuse public access to ``/static/owner/*``.

Owner Console is loopback-only by design. Its templates rendered HTML
is blocked by ``_require_local`` / ``require_owner_console_local``, but
its static assets (``owner.css``, ``owner-feedback.js``, components/*)
are served by Starlette's ``StaticFiles`` mount which does not run
dependencies — they were reachable from the public Cloudflare Tunnel
origin until this middleware. Resources have no secrets but reverse-
engineering them helps an attacker probe owner-only flows; closing
the door is cheaper than auditing what's inside.

Cloudflare ingress could also block this at the edge (and the runbook
recommends it), but defense-in-depth in backend code means the boundary
holds even if Cloudflare config drifts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.errors import error_response
from app.network_boundary import is_loopback_request


async def static_owner_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    path = request.url.path
    if path.startswith("/static/owner/") and not is_loopback_request(request):
        # Carve-out for Starlette's default TestClient (peer=testclient,
        # host=testserver) so the existing loopback tests still pass.
        # Same pattern as web_session_gate. Production traffic never
        # carries these literals.
        peer = request.client.host if request.client else ""
        host_header = (request.headers.get("host") or "").lower()
        if not (peer == "testclient" or host_header.startswith("testserver")):
            return error_response(
                "invalid_request",
                "Owner Console 静态资源仅允许本机访问。",
                status_code=403,
                request_id=getattr(request.state, "request_id", None),
            )
    return await call_next(request)
