"""Opening the Web repayment form must not leave a browser draft nobody wrote.

The repayment form clears its payer deduction while no payer is chosen. Doing
that by dispatching an ``input`` event on an already empty field made the draft
engine save an "unsubmitted" repayment as soon as the page opened, which every
other funds task for the account then offered to continue. The page is the
actual ``/web/funds`` response for a PostgreSQL-backed credit account; the
browser runs the shipped scripts.
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
window.addEventListener("load", () => {
  const drafts = () => Object.keys(localStorage).filter(key => key.startsWith("ticketbox:funds-")).length;
  setTimeout(() => {
    const afterLoad = drafts();
    const principal = document.querySelector("#fund-principal");
    principal.value = "12.30";
    principal.dispatchEvent(new Event("input", {bubbles: true}));
    setTimeout(() => { window.__fundsRepayDraftProbe = {afterLoad, afterTyping: drafts()}; }, 800);
  }, 800);
});
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
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            resource = (STATIC / path.removeprefix("/static/")).resolve()
            if path.startswith("/web/funds"):
                payload, kind, status = body.encode(), "text/html; charset=utf-8", 200
            elif path.startswith("/static/") and resource.is_relative_to(STATIC) and resource.is_file():
                kind = "text/css" if resource.suffix == ".css" else "image/svg+xml" if resource.suffix == ".svg" else "text/javascript"
                payload, status = resource.read_bytes(), 200
            else:
                payload, kind, status = b"not found", "text/plain", 404
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.mark.currency_binding_unbound
def test_opening_the_repayment_form_saves_no_draft_until_the_person_types(installed_funds_web, tmp_path: Path) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_repay_page(installed_funds_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / "funds-repay-browser",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/funds?task=repay",
            width=393, height=900, expression="window.__fundsRepayDraftProbe || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result == {"afterLoad": 0, "afterTyping": 1}
