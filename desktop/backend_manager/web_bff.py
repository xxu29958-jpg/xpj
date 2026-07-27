"""Fail-closed same-origin BFF for the Manager-owned Edge Web product."""

from __future__ import annotations

import http.client
import ipaddress
import urllib.parse
from dataclasses import dataclass
from http.client import HTTPResponse

BRIDGE_HEADER = "X-Ticketbox-Desktop-Bridge"
BRIDGE_VERSION = "v1"
SESSION_COOKIE = "ticketbox_manager_web"
ASSET_SESSION_COOKIE = "ticketbox_manager_assets"
PREFERENCE_SESSION_COOKIE = "ticketbox_manager_preferences"
MAX_REQUEST_BYTES = 65 * 1024 * 1024
_SAFE_RESPONSE_HEADERS = {
    "content-type",
    "content-length",
    "content-disposition",
    "etag",
    "last-modified",
    "location",
    "cache-control",
    "vary",
    "accept-ranges",
    "content-range",
    "content-security-policy",
}
_CLIENT_HEADER_ALLOWLIST = {
    "accept",
    "accept-language",
    "content-type",
    "content-length",
    "if-none-match",
    "if-modified-since",
    "range",
}
_COOKIE_ALLOWLIST = {"xpj_csrf_seed", "ui_theme"}


class WebBridgeError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class BridgeContext:
    backend_origin: str
    app_token: str


@dataclass(frozen=True)
class BridgeResponse:
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes


def allowed_target(raw_target: str, method: str) -> urllib.parse.SplitResult | None:
    if (
        not raw_target.startswith("/")
        or raw_target.startswith("//")
        or "\\" in raw_target
        or any(ord(char) < 0x20 for char in raw_target)
    ):
        return None
    parsed = urllib.parse.urlsplit(raw_target)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return None
    decoded = urllib.parse.unquote(parsed.path)
    if "\\" in decoded or decoded.startswith("//"):
        return None
    if any(part in {".", ".."} for part in decoded.split("/")):
        return None
    if urllib.parse.unquote(decoded) != decoded:
        return None
    verb = method.upper()
    if decoded == "/web" or decoded.startswith("/web/"):
        if decoded == "/web/auth" or decoded.startswith("/web/auth/"):
            return None
        return parsed if verb in {"GET", "HEAD", "POST"} else None
    if decoded.startswith(("/static/web/", "/static/shared/")):
        return parsed if verb in {"GET", "HEAD"} else None
    if decoded == "/api/me/ui-preferences":
        return parsed if verb == "PUT" and not parsed.query else None
    return None


def browser_session_valid(
    cookie_header: str | None,
    expected: str,
    *,
    cookie_name: str = SESSION_COOKIE,
) -> bool:
    if not cookie_header:
        return False
    values = {}
    for part in cookie_header.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator:
            values[name] = value
    return values.get(cookie_name) == expected


def same_origin_request(
    *,
    method: str,
    origin: str | None,
    referer: str | None,
    sec_fetch_site: str | None,
    manager_origin: str,
) -> bool:
    if sec_fetch_site not in {None, "none", "same-origin"}:
        return False
    if method.upper() in {"GET", "HEAD"}:
        return True
    if origin:
        return origin == manager_origin
    if referer:
        return referer == manager_origin or referer.startswith(manager_origin + "/")
    return False


def _filtered_cookie(raw: str | None) -> str | None:
    if not raw:
        return None
    accepted = []
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name in _COOKIE_ALLOWLIST:
            accepted.append(f"{name}={value}")
    return "; ".join(accepted) or None


def _connection(context: BridgeContext) -> tuple[http.client.HTTPConnection, str]:
    parsed = urllib.parse.urlsplit(context.backend_origin)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise WebBridgeError(503, "后端地址无效。") from exc
    if parsed.scheme != "http" or not address.is_loopback or parsed.port is None:
        raise WebBridgeError(503, "桌面桥只允许连接本机后端。")
    return http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=15), parsed.netloc


def relay(
    context: BridgeContext,
    *,
    method: str,
    raw_target: str,
    client_headers,
    body: bytes,
    manager_origin: str,
) -> BridgeResponse:
    target = allowed_target(raw_target, method)
    if target is None:
        raise WebBridgeError(404, "not found")
    if len(body) > MAX_REQUEST_BYTES:
        raise WebBridgeError(413, "request too large")
    connection, backend_host = _connection(context)
    backend_origin = context.backend_origin.rstrip("/")
    headers = {name: value for name, value in client_headers.items() if name.casefold() in _CLIENT_HEADER_ALLOWLIST}
    headers.update(
        {
            "Host": backend_host,
            "Authorization": f"Bearer {context.app_token}",
            BRIDGE_HEADER: BRIDGE_VERSION,
            "Origin": backend_origin,
            "Referer": backend_origin + target.path,
            "Sec-Fetch-Site": "same-origin",
            "Connection": "close",
        }
    )
    cookie = _filtered_cookie(client_headers.get("Cookie"))
    if cookie:
        headers["Cookie"] = cookie
    try:
        connection.request(
            method.upper(),
            urllib.parse.urlunsplit(("", "", target.path, target.query, "")),
            body=body or None,
            headers=headers,
        )
        response: HTTPResponse = connection.getresponse()
        payload = b"" if method.upper() == "HEAD" else response.read()
        response_headers: list[tuple[str, str]] = []
        for name, value in response.getheaders():
            lower = name.casefold()
            if lower in _SAFE_RESPONSE_HEADERS:
                if lower == "location":
                    location = urllib.parse.urlsplit(value)
                    if (
                        location.scheme
                        or location.netloc
                        or not (location.path == "/web" or location.path.startswith("/web/"))
                    ):
                        raise WebBridgeError(502, "后端返回了不安全的跳转。")
                response_headers.append((name, value))
            elif lower == "set-cookie":
                cookie_name = value.partition("=")[0].strip()
                if cookie_name in _COOKIE_ALLOWLIST:
                    response_headers.append(("Set-Cookie", value.replace("Path=/", "Path=/web")))
        return BridgeResponse(
            response.status,
            response.reason,
            tuple(response_headers),
            payload,
        )
    except (OSError, http.client.HTTPException) as exc:
        raise WebBridgeError(503, "小票夹后端尚未就绪。") from exc
    finally:
        connection.close()
