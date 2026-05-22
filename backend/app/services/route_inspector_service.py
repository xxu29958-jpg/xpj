"""Route introspection for the Owner Console API/接口 page.

Walks the FastAPI app's router and groups endpoints by access surface so the
operator can see at a glance:

- which routes are loopback-only (Owner Console)
- which require admin token (admin API)
- which are upload/public surfaces
- which are bootstrap or health probes

This is read-only; it never modifies the running app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from fastapi import FastAPI


_INTERNAL_METHODS = {"HEAD", "OPTIONS"}


@dataclass(frozen=True)
class RouteRow:
    path: str
    methods: tuple[str, ...]
    name: str
    surface: str
    surface_label: str
    surface_class: str  # css class name


@dataclass(frozen=True)
class RouteGroup:
    surface: str
    label: str
    description: str
    css_class: str
    rows: list[RouteRow] = field(default_factory=list)


_GROUPS: tuple[tuple[str, str, str, str], ...] = (
    ("owner", "Owner Console（仅本机）", "本机环回 + Host 头双重校验，公网不可达。", "surface-owner"),
    ("admin", "Admin API（管理 token）", "通常只在本机 + admin token 才能调用，可通过 ALLOW_PUBLIC_ADMIN_API 放开（不建议）。", "surface-admin"),
    ("upload", "上传接口（公网，按 token / Key 校验）", "iPhone 快捷指令 / Android 客户端通过 Cloudflare Tunnel 访问。", "surface-upload"),
    ("web", "网页版账本（/web）", "本机环回 + Host 头双重校验，公网不可达；桌面浏览器使用的账本流。", "surface-web"),
    ("bootstrap", "首次绑定 / 引导", "受 ENABLE_HTTP_BOOTSTRAP 与 secret 控制，绑定完成后建议关闭。", "surface-bootstrap"),
    ("public", "其他公开端点", "/api/health 等无需鉴权的状态查询。", "surface-public"),
    ("docs", "OpenAPI 文档", "默认 ENABLE_API_DOCS=false 时不会挂载。", "surface-docs"),
    ("static", "静态资源", "Owner Console / Web 版的 CSS、图片等。", "surface-static"),
)


def _classify(path: str) -> tuple[str, str, str]:
    if path.startswith("/owner"):
        return ("owner", "Owner Console（仅本机）", "surface-owner")
    if path.startswith("/api/admin"):
        return ("admin", "Admin API（管理 token）", "surface-admin")
    if path.startswith("/api/bootstrap"):
        return ("bootstrap", "首次绑定 / 引导", "surface-bootstrap")
    if path.startswith("/api/uploads") or path.startswith("/u/") or path == "/u":
        return ("upload", "上传接口（公网，按 token / Key 校验）", "surface-upload")
    if path.startswith("/web"):
        return ("web", "网页版账本（/web）", "surface-web")
    if path.startswith("/static"):
        return ("static", "静态资源", "surface-static")
    if path in {"/openapi.json", "/docs", "/redoc"}:
        return ("docs", "OpenAPI 文档", "surface-docs")
    return ("public", "其他公开端点", "surface-public")


def list_route_groups(app: FastAPI) -> list[RouteGroup]:
    """Build grouped route rows for display in the Owner Console."""
    groups: dict[str, RouteGroup] = {}
    for key, label, desc, css in _GROUPS:
        groups[key] = RouteGroup(surface=key, label=label, description=desc, css_class=css)

    for route in app.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        # Mounts (e.g. /static) expose a single entry without HTTP methods.
        methods: Iterable[str] = getattr(route, "methods", None) or ()
        methods = tuple(sorted(m for m in methods if m not in _INTERNAL_METHODS))
        name = getattr(route, "name", "") or ""
        surface, label, css = _classify(path)
        groups[surface].rows.append(
            RouteRow(
                path=path,
                methods=methods or ("MOUNT",),
                name=name,
                surface=surface,
                surface_label=label,
                surface_class=css,
            )
        )

    # Sort rows for stable display
    out: list[RouteGroup] = []
    for key, _label, _desc, _css in _GROUPS:
        g = groups[key]
        g.rows.sort(key=lambda r: (r.path, r.methods))
        out.append(g)
    return out


def count_routes(groups: list[RouteGroup]) -> int:
    return sum(len(g.rows) for g in groups)
