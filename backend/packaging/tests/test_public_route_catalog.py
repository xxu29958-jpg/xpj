"""Real route/consumer coverage for the reviewed public ingress catalogue."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.public_surface import (
    AUTH_DESCRIPTIONS,
    catalog_markdown,
    remote_ingress_config,
    route_catalog,
)

ROOT = Path(__file__).resolve().parents[3]


def _template(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{id}", path)


def _sample(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "123", path)


def _forwards(config: dict, path: str) -> bool:
    return any(re.fullmatch(rule["path"], path) for rule in config["ingress"][:-1])


def test_catalog_classifies_every_real_registered_method_path_once() -> None:
    # Import registers routes only. No lifespan, TestClient, or database I/O.
    from fastapi.routing import APIRoute

    from app.main import app

    registered = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    reviewed = [(route.method, route.path) for route in route_catalog()]
    assert len(reviewed) == len(set(reviewed))
    assert set(reviewed) == registered
    assert {route.authentication for route in route_catalog()} <= AUTH_DESCRIPTIONS.keys()


def test_catalog_covers_actual_android_api_methods_and_excludes_private_status() -> None:
    reviewed = {(row.method, _template(row.path)): row for row in route_catalog()}
    declared = []
    for source in (ROOT / "android/app/src/main").rglob("*.kt"):
        for method, path in re.findall(r'@(GET|POST|PUT|PATCH|DELETE|HEAD)\("([^"]+)"\)', source.read_text(encoding="utf-8")):
            declared.append((method, "/" + path.lstrip("/")))
    assert len(declared) >= 200
    for method, path in declared:
        row = reviewed[(method, _template(path.split("?", 1)[0]))]
        # This existing local diagnostic consumer is intentionally unavailable
        # over the public Tunnel; it must not turn private status into an API family.
        assert row.exposed is (path != "/api/status/private"), (method, path)


def test_ingress_forwards_every_reviewed_public_path_and_no_private_route() -> None:
    config = remote_ingress_config("https://ticketbox.example.com", 8231)
    for row in route_catalog():
        assert _forwards(config, _sample(row.path)) is row.exposed, row
    assert config["ingress"][-1] == {"service": "http_status:404"}
    assert all(rule["hostname"] == "ticketbox.example.com" for rule in config["ingress"][:-1])
    assert all(rule["service"] == "http://127.0.0.1:8231" for rule in config["ingress"][:-1])
    assert all(set(rule) == {"hostname", "path", "service"} for rule in config["ingress"][:-1])


@pytest.mark.parametrize("path", [
    "/api", "/api/new-unreviewed", "/api/auth/desktop/activate", "/api/health/installation",
    "/api/status/private", "/owner/settings", "/desktop/session/revoke", "/docs", "/redoc",
    "/openapi.json", "/uploads/file.png", "/static/uploads/file.png", "/static/owner/app.js",
    "/metrics", "/diag/tunnel", "/web/auth/local", "/web/currency-adoption",
    "/api/expenses/123/original/unknown", "/web/unreviewed-page",
])
def test_unreviewed_and_private_paths_do_not_enter_ingress(path: str) -> None:
    assert not _forwards(remote_ingress_config("https://ticketbox.example.com", 8000), path)


@pytest.mark.parametrize("path", ["/static/web/app.js", "/static/shared/tokens.css"])
def test_only_product_static_subtrees_enter_ingress(path: str) -> None:
    assert _forwards(remote_ingress_config("https://ticketbox.example.com", 8000), path)


@pytest.mark.parametrize("origin", [
    "http://example.com", "https://example.com/path", "https://example.com?q=1", "https://example.com#x",
    "https://user:secret@example.com", "https://example.com:8443", "https://127.0.0.1",
    "http://localhost", "https://localhost", "https://x.localhost", "https://*.example.com",
])
def test_ingress_reuses_settings_origin_rules_and_requires_one_public_hostname(origin: str) -> None:
    from app.errors import AppError

    with pytest.raises((AppError, ValueError)):
        remote_ingress_config(origin, 8000)


def test_reviewed_docs_are_rendered_from_the_same_catalog() -> None:
    assert (ROOT / "docs/runbook/PUBLIC_ROUTE_CATALOG.md").read_text(encoding="utf-8") == catalog_markdown()
