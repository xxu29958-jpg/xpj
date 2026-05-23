"""Optional Cloudflare Access origin JWT gate for public browser routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.errors import error_response
from app.network_boundary import is_loopback_request
from app.services.cloudflare_access_service import (
    CloudflareAccessVerificationError,
    verify_cloudflare_access_jwt,
)


def _requires_cloudflare_access(request: Request) -> bool:
    if is_loopback_request(request):
        return False
    path = request.url.path
    return (
        path == "/web"
        or path.startswith("/web/")
        or path.startswith("/static/web/")
        or path.startswith("/static/shared/")
    )


async def cloudflare_access_guard(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if not get_settings().cloudflare_access_required or not _requires_cloudflare_access(request):
        return await call_next(request)

    cfg = get_settings()
    if not cfg.cloudflare_access_team_domain or not cfg.cloudflare_access_aud:
        return error_response(
            "server_error",
            "Cloudflare Access 已要求启用，但后端缺少 Team Domain 或 AUD 配置。",
            status_code=503,
            request_id=getattr(request.state, "request_id", None),
        )

    token = (request.headers.get("cf-access-jwt-assertion") or "").strip()
    if not token:
        return error_response(
            "cloudflare_access_required",
            "请先通过 Cloudflare Access 验证身份。",
            status_code=403,
            request_id=getattr(request.state, "request_id", None),
        )
    try:
        claims = verify_cloudflare_access_jwt(
            token,
            team_domain=cfg.cloudflare_access_team_domain,
            audience=cfg.cloudflare_access_aud,
        )
    except CloudflareAccessVerificationError:
        return error_response(
            "cloudflare_access_invalid",
            "Cloudflare Access 身份令牌无效。",
            status_code=403,
            request_id=getattr(request.state, "request_id", None),
        )
    request.state.cloudflare_access_claims = claims
    return await call_next(request)


__all__ = ["cloudflare_access_guard"]
