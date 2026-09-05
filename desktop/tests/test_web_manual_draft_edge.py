"""Cloud Windows gate: shipped Web draft scripts, real origin/locks/native POST.

The small HTTP consumer supplies synthetic form/ack metadata, not financial
facts. Backend real-db tests bind that metadata to the actual command owner;
read-only production-template previews cover layout. No database is started here.
"""

from __future__ import annotations

import html
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from backend_manager.desktop_shell import discover_edge_executable
from tests._edge_cdp import evaluate_page

_ROOT = Path(__file__).resolve().parents[2]
_WEB = _ROOT / "backend/app/static/web"
_SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "ledger", "deviceId": "device"}
_VALUES = {"amount_major": "", "currency_code": "CNY", "merchant": "", "category": "其他", "spent_at": "2026-09-06T12:30", "note": ""}

pytestmark = pytest.mark.skipif(os.name != "nt", reason="cloud Windows Edge consumer")


def _form(query: dict[str, list[str]]) -> bytes:
    scope = {key: query.get(key, [value])[0] for key, value in _SCOPE.items()}
    inputs = "".join(
        f'<label>{name}<input name="{name}" value="{html.escape(value)}"></label>'
        for name, value in _VALUES.items() if name != "currency_code"
    )
    setup = ""
    if "noStorage" in query:
        setup = "Object.defineProperty(window, 'localStorage', {get() {throw Error('denied');}});"
    if "noLocks" in query:
        setup = "Object.defineProperty(navigator, 'locks', {value: undefined});"
    return f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<form method="post" action="/submit" data-manual-draft-scope="{html.escape(json.dumps(scope))}" data-manual-draft-result="">
  <input name="client_ref" type="hidden" value="{uuid4().hex}">
  <input name="csrf_token" type="hidden" value="synthetic-not-a-credential">
  <fieldset data-manual-edit-fields>
    {inputs}<select name="currency_code"><option>CNY</option><option>EUR</option></select>
    <details open data-manual-options data-start-expanded="false"><summary hidden>补充资料</summary></details>
  </fieldset>
  <button type="submit" data-manual-submit>记下这笔支出</button>
  <p hidden data-manual-draft-status></p>
</form>
<div hidden data-manual-draft-actions><a href="/form">另记一笔</a></div>
<details hidden data-manual-draft-shelf><span data-manual-draft-count></span><ul data-manual-draft-list></ul></details>
<script>{setup}</script>
<script src="/manual-drafts.js"></script><script src="/manual-entry.js"></script>
</body></html>""".encode()


def test_real_edge_manual_intent_survives_reload_and_unknown_response(tmp_path: Path) -> None:
    edge = discover_edge_executable()
    if edge is None:
        pytest.skip("Microsoft Edge is required")
    posts: list[dict[str, list[str]]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def reply(self, body: bytes, *, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/":
                self.reply(b'<!doctype html><html><head><meta charset="utf-8"></head><body>'
                           b'<script src="/manual-drafts.js"></script><script src="/probe.js"></script></body></html>')
            elif url.path == "/form":
                self.reply(_form(parse_qs(url.query)))
            elif url.path in {"/manual-drafts.js", "/manual-entry.js", "/manual-draft-ack.js"}:
                self.reply((_WEB / url.path.removeprefix("/")).read_bytes(), content_type="text/javascript")
            elif url.path == "/probe.js":
                self.reply((Path(__file__).parent / "fixtures/web_manual_draft_probe.js").read_bytes(), content_type="text/javascript")
            else:
                self.reply(b"not found", status=404)

        def do_POST(self) -> None:
            assert self.path == "/submit"
            form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode(), keep_blank_values=True)
            posts.append(form)
            if len(posts) == 1:
                self.reply(b"<p>synthetic unknown response</p>", status=503)
                return
            ack = html.escape(json.dumps({"scope": _SCOPE, "clientRef": form["client_ref"][0]}))
            self.reply((f'<span data-manual-draft-ack="{ack}"></span><p hidden data-manual-draft-ack-status></p>'
                        '<script src="/manual-drafts.js"></script><script src="/manual-draft-ack.js"></script>').encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = evaluate_page(
            edge, profile=tmp_path / "edge-manual-drafts", url=f"http://127.0.0.1:{server.server_port}/",
            width=360, height=800, expression="window.__manualDraftProbe || undefined",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result == {"reload": True, "lock": True, "retry": True, "ack": True, "quarantine": True, "storage": True}
    assert len(posts) == 2
    assert posts[0] == posts[1]
    assert posts[0]["amount_major"] == ["28.50"]
    assert posts[0]["currency_code"] == ["EUR"]
    assert posts[0]["note"] == ["合成备注"]
