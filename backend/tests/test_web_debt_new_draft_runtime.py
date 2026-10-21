"""Opening "新建往来" must not leave a browser draft nobody wrote.

The debt-creation form asked the draft engine to retain its selection on
mount, but the page opens with nothing selected, so every visit saved an empty
"新建 · 未命名往来 · 未提交" draft that the debts and receivables pages then
listed as unfinished. The page is the actual ``/web/debts/new`` response; the
browser runs the shipped scripts.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.routes.web_auth import SESSION_COOKIE_NAME
from tests import _web_browser_test_support as browser_runtime
from tests._local_web_identity_support import _connect_local_session, installed_web_setup

STATIC = (Path(__file__).resolve().parents[1] / "app/static").resolve()
PROBE = """<script>
const request = navigator.locks.request.bind(navigator.locks);
navigator.locks.request = (...args) => new Promise(resolve =>
  setTimeout(() => resolve(request(...args)), 1800));
window.addEventListener("load", async () => {
  const drafts = () => Object.keys(localStorage).filter(key => key.startsWith("ticketbox:debtcreation-")).length;
  const who = document.querySelector("[name=counterparty_label]");
  while (who.readOnly || who.disabled) await new Promise(resolve => setTimeout(resolve, 25));
  const afterLoad = drafts();
  who.value = "朋友丙";
  who.dispatchEvent(new Event("input", {bubbles: true}));
  window.__debtNewDraftProbe = {afterLoad, afterTyping: drafts()};
});
</script></body>"""


@pytest.fixture()
def installed_debt_web():
    yield from installed_web_setup()


def _debt_new_page(installed) -> str:
    token = _connect_local_session(installed, next_url="/web/debts")
    page = installed.browser.get("/web/debts/new", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert page.status_code == 200 and "data-debtcreation-draft-scope" in page.text, page.text[:500]
    return page.text.replace("</body>", PROBE)


def _serve(body: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            resource = (STATIC / path.removeprefix("/static/")).resolve()
            if path == "/web/debts/new":
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


def test_opening_the_debt_form_saves_no_draft_until_the_person_types(installed_debt_web, tmp_path: Path) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_debt_new_page(installed_debt_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / "debt-new-browser",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/debts/new",
            width=393, height=900, expression="window.__debtNewDraftProbe || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result == {"afterLoad": 0, "afterTyping": 1}
