"""A long account balance stays one readable number on a phone-width page.

At 360px the balance card's amount used to break between digits
("¥87,654,321,09" / "8.76"). It now shrinks to fit its card on one line;
short amounts keep their size. The page is the actual ``/web/funds`` response
for a PostgreSQL-backed account and the browser runs the shipped styles.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.middleware.csrf import CSRF_COOKIE_NAME
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests import _web_browser_test_support as browser_runtime
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms

STATIC = (Path(__file__).resolve().parents[1] / "app/static").resolve()
PROBE = """<script>
window.addEventListener("load", () => setTimeout(() => {
  const amount = document.querySelector(".funds-summary .product-amount");
  const style = getComputedStyle(amount), card = amount.parentElement;
  const right = card.getBoundingClientRect().right - parseFloat(getComputedStyle(card).paddingRight);
  window.__fundsLongAmount = {text: amount.textContent, lines: Math.round(amount.getBoundingClientRect().height / parseFloat(style.lineHeight)),
    overflow: amount.scrollWidth - amount.clientWidth, outside: Math.round(amount.getBoundingClientRect().right - right)};
}, 300));
</script></body>"""


@pytest.fixture()
def installed_funds_web():
    yield from installed_web_setup()


def _account_pages(installed) -> dict[str, str]:
    token = _connect_local_session(installed, next_url="/web/funds")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/funds?task=create", headers={"Cookie": cookie})
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000", "Accept": "application/json"}
    pages = {}
    for name, opening in (("long", "87654321098.76"), ("short", "37.90")):
        fields = hidden_post_forms(installed.browser.get("/web/funds?task=create", headers=headers).text)["/web/funds/save"]
        fields.update(name=f"{name}卡", kind="bank", currency_code="CNY", opening_amount=opening, visibility="private",
            opening_source="本人对账", occurred_on="2026-10-18", institution="", tail="")
        created = installed.browser.post("/web/funds/save", data=fields, headers=headers)
        assert created.status_code == 200, created.text
        detail = installed.browser.get(f"/web/funds?account_id={created.json()['receipt']['public_id']}", headers=headers)
        assert detail.status_code == 200 and "funds-summary" in detail.text, detail.text[:500]
        pages[name] = detail.text.replace("</body>", PROBE)
    return pages


def _serve(pages: dict[str, str]):
    types = {".css": "text/css", ".svg": "image/svg+xml", ".js": "text/javascript"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            resource = (STATIC / url.path.removeprefix("/static/")).resolve()
            name = parse_qs(url.query).get("case", [""])[0]
            if url.path == "/web/funds" and name in pages:
                payload, kind, status = pages[name].encode(), "text/html; charset=utf-8", 200
            elif url.path.startswith("/static/") and resource.is_relative_to(STATIC) and resource.is_file():
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
def test_long_and_short_balances_each_stay_on_one_line_at_phone_width(installed_funds_web, tmp_path: Path) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_account_pages(installed_funds_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        results = {name: browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / f"long-amount-{name}",
            prepare_url=lambda _, name=name: f"http://127.0.0.1:{server.server_port}/web/funds?case={name}",
            width=360, height=760, expression="window.__fundsLongAmount || undefined") for name in ("long", "short")}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert results["long"] == {"text": "¥87,654,321,098.76", "lines": 1, "overflow": 0, "outside": 0}, results
    assert results["short"] == {"text": "¥37.90", "lines": 1, "overflow": 0, "outside": 0}, results
