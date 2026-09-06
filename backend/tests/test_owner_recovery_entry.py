"""Owner recovery uses the existing business surface and a real Web identity."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from app.middleware.csrf import CSRF_COOKIE_NAME
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._infra.merchant_catalog import create_catalog
from tests._local_web_identity_support import (
    _connect_local_session,
    _InstalledWeb,
    installed_web_setup,
)


def _recovery_href(html: str) -> str:
    link = re.search(r'<a href="([^"]*/recycle-bin)"[^>]*>回收站</a>', html)
    assert link is not None, "The Owner recovery entry must be reachable"
    return link.group(1)


def test_owner_recovery_entry_targets_business_surface() -> None:
    owner_templates = Path(__file__).resolve().parents[1] / "app/templates/owner"
    environment = Environment(loader=FileSystemLoader(owner_templates), autoescape=True)
    html = environment.get_template("_sidebar_nav.html").render(
        request=SimpleNamespace(url=SimpleNamespace(path="/owner")), backend_version="test"
    )
    assert _recovery_href(html) == "/web/recycle-bin"
    assert 'href="/owner/ledgers"' in html


@pytest.fixture()
def installed_web() -> Iterator[_InstalledWeb]:
    yield from installed_web_setup()


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_owner_entry_restores_merchant_through_real_web_identity(installed_web: _InstalledWeb) -> None:
    browser = installed_web.browser
    owner = browser.get("/owner")
    assert owner.status_code == 200
    recovery_url = _recovery_href(owner.text)
    entry = browser.get(recovery_url, follow_redirects=False)
    assert entry.status_code == 303
    assert entry.headers["location"].startswith("/web/auth/local?")
    token = _connect_local_session(installed_web, next_url=recovery_url)
    headers = {"Authorization": f"Bearer {token}"}
    merchant = create_catalog(browser, headers, display_name="恢复入口商家")
    deleted = browser.request(
        "DELETE", f"/api/merchants/catalog/{merchant['public_id']}", headers=headers,
        json={"expected_row_version": merchant["row_version"]},
    )
    assert deleted.status_code == 200
    # HTTPX does not send Secure cookies over this loopback HTTP test transport.
    # Carry the real issued session, as the existing local-identity tests do.
    session_headers = {"Cookie": (
        f"{CSRF_COOKIE_NAME}={browser.cookies.get(CSRF_COOKIE_NAME)}; {SESSION_COOKIE_NAME}={token}"
    )}
    page = browser.get(recovery_url, headers=session_headers, follow_redirects=False)
    assert page.status_code == 200
    assert "恢复入口商家" in page.text
    form = re.search(r'<form[^>]*action="/web/recycle-bin/restore"[^>]*>(.*?)</form>', page.text, re.DOTALL)
    assert form is not None
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', form.group(1)))
    assert fields["kind"] == "merchant_catalog"
    assert fields["ledger_id"] == installed_web.shared_ledger_id
    assert fields["resource_id"] == merchant["public_id"]
    origin = {**session_headers, "Origin": "http://127.0.0.1:8000"}
    assert browser.get("/owner/recycle-bin").status_code == 404
    assert browser.post("/owner/recycle-bin/restore", data=fields, headers=origin).status_code == 404
    stale = {**fields, "expected_row_version": str(int(fields["expected_row_version"]) + 1)}
    conflict = browser.post("/web/recycle-bin/restore", data=stale, headers=origin)
    assert conflict.status_code == 422
    assert "页面已过期" in conflict.text
    restored = browser.post("/web/recycle-bin/restore", data=fields, headers=origin, follow_redirects=False)
    assert restored.status_code == 303
    items = browser.get("/api/merchants/catalog", headers=headers).json()["items"]
    assert [item["public_id"] for item in items] == [merchant["public_id"]]
    assert browser.get("/owner/ledgers").status_code == 200
