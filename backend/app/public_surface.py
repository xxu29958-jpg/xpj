"""Read the reviewed public route policy and render remote Tunnel ingress.

The result is a configuration for the account owner to apply in Cloudflare.
It is not a local enforcement receipt: remote config can change at any time.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from app.public_route_catalog import ROUTE_GROUPS

PRIVATE_AUTH_CLASSES = frozenset({"local_only", "private_status", "retired"})
AUTH_DESCRIPTIONS = {
    "app_session": "App Bearer；Backend 继续执行角色、账本和设备隔离",
    "pairing_proof": "连接码 + 幂等绑定证明；限流；不需要既有 Bearer",
    "refresh_proof": "当前/恢复期 App 凭证 + 刷新证明；不允许网页挑战",
    "upload_link": "专用 UploadLink capability；有效期、次数、大小和 MIME 限制",
    "invitation": "邀请 capability；提交已有会话时还需验证该会话",
    "browser_pairing": "Web 连接码与绑定证明；表单 CSRF",
    "browser_invitation": "Web 邀请 capability 与绑定证明；表单 CSRF",
    "browser_logout": "撤销当前 Web cookie 会话；表单 CSRF；无会话时清 cookie",
    "browser_session": "Web HttpOnly cookie；写操作 CSRF；角色与账本隔离",
    "health": "匿名最小健康结果，不含安装或数据身份",
    "local_only": "不进公网 ingress；原有本机/Owner/Desktop 权限边界继续执行",
    "private_status": "私有运行信息，保留 App 鉴权，但不进公网 ingress",
    "retired": "已退役上传入口；不进公网 ingress",
}


@dataclass(frozen=True)
class PublicRoute:
    method: str
    path: str
    authentication: str

    @property
    def exposed(self) -> bool:
        return self.authentication not in PRIVATE_AUTH_CLASSES


@lru_cache(maxsize=1)
def route_catalog() -> tuple[PublicRoute, ...]:
    return tuple(
        PublicRoute(*line.split(" ", 1), authentication)
        for authentication, lines in ROUTE_GROUPS.items()
        for line in lines.splitlines() if line
    )


def path_pattern(path: str) -> str:
    """RE2-compatible anchored path; path variables cannot consume a slash."""
    return "^" + "".join(
        "[^/]+" if part.startswith("{") else re.escape(part)
        for part in re.split(r"(\{[a-z_]+\})", path)
    ) + "$"


def managed_public_hostname(public_origin: str) -> str:
    # Reuse the Backend settings owner instead of adding another URL authority.
    from app.services.runtime_settings_service import _validate_public_base_url

    parsed = urlsplit(_validate_public_base_url(public_origin))
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.port not in {None, 443}:
        raise ValueError("managed Tunnel requires an HTTPS hostname on port 443")
    labels = hostname.split(".")
    if (
        len(labels) < 2 or len(hostname) > 253 or hostname.endswith(".localhost")
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("managed Tunnel requires a valid public DNS hostname")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    raise ValueError("managed Tunnel requires a DNS hostname, not an IP address")


def remote_ingress_config(public_origin: str, backend_port: int) -> dict:
    if isinstance(backend_port, bool) or not 1 <= backend_port <= 65535:
        raise ValueError("invalid installed Backend port")
    hostname = managed_public_hostname(public_origin)
    # Group by path family for a readable, bounded collection of RE2 matchers.
    families: dict[str, set[str]] = {}
    for route in route_catalog():
        if route.exposed:
            family = "/".join(route.path.split("/")[:3])
            families.setdefault(family, set()).add(path_pattern(route.path)[1:-1])
    families["/static/shared"] = {r"/static/shared/[^?]+"}
    families["/static/web"] = {r"/static/web/[^?]+"}
    rules = [
        {"hostname": hostname, "path": "^(" + "|".join(sorted(paths)) + ")$",
         "service": f"http://127.0.0.1:{backend_port}"}
        for _, paths in sorted(families.items())
    ]
    return {"ingress": [*rules, {"service": "http_status:404"}]}


def catalog_markdown() -> str:
    lines = [
        "# 公网路径与方法清单", "",
        "由 `backend/app/public_route_catalog.py` 经 `backend/scripts/render_public_routes.py` 生成。",
        "这是审核后的路径策略，不是自动公开 OpenAPI。新增路由必须明确分类；测试比较真实注册路由与此清单。",
        "", "Cloudflare ingress 只匹配 hostname/path；方法、鉴权、角色、账本隔离与 CSRF 继续由 Backend 执行。",
        "静态资源仅允许 `GET/HEAD /static/web/*` 与 `/static/shared/*`；不允许 `/static/owner/*`、上传目录、文档或 metrics。",
        "远端必须保留公网 Host，不得设置 loopback Host override。可选 Access 只覆盖 Web 和其静态资源，不能挑战原生 API 或 UploadLink。",
        "", "| 方法 | 路径 | 公网 | 鉴权/责任 |", "| --- | --- | --- | --- |",
    ]
    for route in sorted(route_catalog(), key=lambda row: (row.path, row.method)):
        lines.append(
            f"| {route.method} | `{route.path}` | {'允许' if route.exposed else '拒绝'} | "
            f"{AUTH_DESCRIPTIONS[route.authentication]} |"
        )
    return "\n".join(lines) + "\n"
