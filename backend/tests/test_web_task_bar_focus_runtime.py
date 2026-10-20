"""Focusing a field on a phone-width task page never leaves it under the sticky action bar.

On a 360px screen the funds task bar wraps to about three rows (~160px) while
the page reserved a fixed 88px for focus scrolling, so keyboard "next" or Tab
into the repayment principal left the field hidden behind the bar. The page is
the actual ``/web/funds`` response for a PostgreSQL-backed credit account and
the browser runs the shipped styles and scripts.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.middleware.csrf import CSRF_COOKIE_NAME
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests import _web_browser_test_support as browser_runtime
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms

STATIC = (Path(__file__).resolve().parents[1] / "app/static").resolve()
PROBE = """<script>
window.addEventListener("load", () => setTimeout(() => {
  const bar = document.querySelector("form .product-task-actions");
  const covered = [];
  for (const field of document.querySelectorAll("form .product-field :is(input, select, textarea)")) {
    if (field.type === "hidden" || field.disabled || field.closest("[hidden], details:not([open])")) continue;
    window.scrollTo(0, 0);
    field.focus();
    if (field.getBoundingClientRect().bottom > bar.getBoundingClientRect().top + 1) covered.push(field.name);
  }
  window.__taskBarFocusProbe = {covered, barHeight: Math.round(bar.getBoundingClientRect().height)};
}, 600));
</script></body>"""


@pytest.fixture()
def installed_funds_web():
    yield from installed_web_setup()


def _repay_page(installed) -> str:
    token = _connect_local_session(installed, next_url="/web/funds")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/funds?task=create", headers={"Cookie": cookie})
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000", "Accept": "application/json"}
    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(name="浏览器信用账户", kind="credit", currency_code="CNY", opening_amount="0", visibility="private",
        opening_source="本人对账", occurred_on="2026-10-18", institution="", tail="")
    created = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert created.status_code == 200, created.text
    account = created.json()["receipt"]["public_id"]
    repay = installed.browser.get(f"/web/funds?task=repay&account_id={account}", headers=headers)
    assert repay.status_code == 200 and "data-funds-form" in repay.text, repay.text[:500]
    return repay.text.replace("</body>", PROBE)


def _serve(body: str):
    types = {".css": "text/css", ".svg": "image/svg+xml", ".js": "text/javascript"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            resource = (STATIC / path.removeprefix("/static/")).resolve()
            if path.startswith("/web/funds"):
                payload, kind, status = body.encode(), "text/html; charset=utf-8", 200
            elif path.startswith("/static/") and resource.is_relative_to(STATIC) and resource.is_file():
                payload, kind, status = resource.read_bytes(), types.get(resource.suffix, "application/octet-stream"), 200
            else:
                payload, kind, status = b"not found", "text/plain", 404
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.mark.currency_binding_unbound
def test_phone_width_focus_keeps_every_repayment_field_above_the_task_bar(installed_funds_web, tmp_path: Path) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_repay_page(installed_funds_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / "task-bar-focus",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/funds?task=repay",
            width=360, height=640, expression="window.__taskBarFocusProbe || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    # The bar really wraps at this width; otherwise the check would prove nothing.
    assert result["barHeight"] > 120, result
    assert result["covered"] == [], result
