"""The expense form's currency controls show their whole text on a phone.

The amount and currency sat in two ~130px columns at 360px, so the currency
search read "搜索币种名称" and the select "CNY · 人民" — on every phone width and
text size. The row now stacks on phones and stays side by side on wider screens.
The page is the actual ``/web/expenses/new`` response; the browser runs the
shipped styles and the currency picker.
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
window.addEventListener("load", () => setTimeout(() => {
  const money = document.querySelector(".manual-expense-money");
  const clipped = [...money.querySelectorAll("input, select")].filter(el => el.offsetParent).map(el => {
    const style = getComputedStyle(el), probe = document.createElement("span");
    probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${style.font}`;
    probe.textContent = el.tagName === "SELECT" ? el.selectedOptions[0].textContent.trim() : (el.value || el.placeholder);
    document.body.append(probe);
    const room = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - (el.tagName === "SELECT" ? 24 : 0);
    const over = Math.round(probe.getBoundingClientRect().width - room);
    probe.remove();
    return over > 1 ? (el.name || "currency-search") : null;
  }).filter(Boolean);
  window.__expenseCurrencyFit = {clipped, columns: getComputedStyle(money).gridTemplateColumns.split(" ").filter(size => size !== "0px").length};
}, 500));
</script></body>"""


@pytest.fixture()
def installed_expense_web():
    yield from installed_web_setup()


def _expense_page(installed) -> str:
    token = _connect_local_session(installed, next_url="/web/expenses/new")
    page = installed.browser.get("/web/expenses/new", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert page.status_code == 200 and "manual-expense-money" in page.text, page.text[:500]
    return page.text.replace("</body>", PROBE)


def _serve(body: str):
    types = {".css": "text/css", ".svg": "image/svg+xml", ".js": "text/javascript"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            resource = (STATIC / url.path.removeprefix("/static/")).resolve()
            if url.path == "/web/expenses/new":
                payload, kind, status = body.encode(), "text/html; charset=utf-8", 200
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


@pytest.mark.parametrize(("width", "columns"), [(360, 1), (768, 2)])
def test_currency_controls_fit_at_phone_width_and_sit_beside_the_amount_when_wide(
        installed_expense_web, tmp_path: Path, width: int, columns: int) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_expense_page(installed_expense_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / f"expense-currency-{width}",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/expenses/new",
            width=width, height=900, expression="window.__expenseCurrencyFit || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result == {"clipped": [], "columns": columns}, result
