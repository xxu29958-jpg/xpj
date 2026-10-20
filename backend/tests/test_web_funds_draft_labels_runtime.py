"""Unfinished funds tasks on one account each say which task they continue.

The browser keeps every unsubmitted funds task and lists them on the funds
pages. Every entry used to read "继续资金任务 · <account> · 未提交", so a
repayment and a fee started on the same credit account were indistinguishable.
The pages are the actual ``/web/funds`` responses for a PostgreSQL-backed
credit account; the browser runs the shipped scripts and walks repay → fee → edit.
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
// Exercise slow lease startup: programmatic writes must not bypass a read-only form.
if (new URLSearchParams(location.search).get("task") === "repay") {
  const request = navigator.locks.request.bind(navigator.locks);
  navigator.locks.request = (...args) => new Promise(resolve =>
    setTimeout(() => resolve(request(...args)), 1800));
}
window.addEventListener("load", async () => {
  const task = new URLSearchParams(location.search).get("task");
  const editable = async selector => {
    let field;
    while (!(field = document.querySelector(selector)) || field.readOnly || field.disabled) {
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    return field;
  };
  const type = async (selector, value) => {
    const field = await editable(selector);
    field.value = value;
    field.dispatchEvent(new Event("input", {bubbles: true}));
  };
  if (task === "repay") {
    await type("#fund-principal", "10.00");
    location.assign("/web/funds?task=incur_fee");
  } else if (task === "incur_fee") {
    await type("[name=activity_amount]", "2.00");
    location.assign("/web/funds?task=edit");
  } else {
    await editable("#fund-name");
    window.__fundsDraftLabels = [...document.querySelectorAll("[data-funds-draft-list] a")]
      .map(link => [link.textContent, new URL(link.href).searchParams.get("task")]).sort();
  }
});
</script></body>"""


@pytest.fixture()
def installed_funds_web():
    yield from installed_web_setup()


def _task_pages(installed) -> dict[str, str]:
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
    pages = {}
    for task in ("repay", "incur_fee", "edit"):
        response = installed.browser.get(f"/web/funds?task={task}&account_id={account}", headers=headers)
        assert response.status_code == 200 and "data-funds-form" in response.text, response.text[:500]
        pages[task] = response.text.replace("</body>", PROBE)
    return pages


def _serve(pages: dict[str, str]):
    types = {".css": "text/css", ".svg": "image/svg+xml", ".js": "text/javascript"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            resource = (STATIC / url.path.removeprefix("/static/")).resolve()
            task = parse_qs(url.query).get("task", [""])[0]
            if url.path == "/web/funds" and task in pages:
                payload, kind, status = pages[task].encode(), "text/html; charset=utf-8", 200
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
def test_two_unfinished_tasks_on_one_account_are_named_by_task(installed_funds_web, tmp_path: Path) -> None:
    browser = browser_runtime._discover_database_browser()
    server = _serve(_task_pages(installed_funds_web))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser, profile=tmp_path / "funds-draft-labels",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/funds?task=repay",
            width=393, height=900, expression="window.__fundsDraftLabels || undefined",
            document_url_prefix=f"http://127.0.0.1:{server.server_port}/web/funds?task=edit", result_timeout=20.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result == [["继续记录已发生费用 · 浏览器信用账户 · 未提交", "incur_fee"],
                      ["继续记录还款 · 浏览器信用账户 · 未提交", "repay"]]
