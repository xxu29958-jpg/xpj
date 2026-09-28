"""Actual planning forms retain original raw input after browser refresh; no financial database claim."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.routes._web_recurring_presenter import apply_form_draft
from app.routes.web_budgets import _budget_view
from app.services.currency_common import currency_input_metadata
from tests.test_budget_currency_presenters import _budget
from tests.test_web_edge_runtime_contract import _discover_edge, _edge_cdp
from tests.test_web_recurring_history_view import listing_context

ROOT = Path(__file__).resolve().parents[2]

ENV = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
                '{% block page_scripts %}{% endblock %}</head><body>'
                '{% block content %}{% endblock %}</body></html>'}),
    FileSystemLoader(ROOT / "backend/app/templates/web"),
]), autoescape=select_autoescape(["html"]))
HITS = {}
MISSING = []
POSTS = []


def render(kind):
    HITS[kind] = HITS.get(kind, 0) + 1
    key = str(uuid4())
    scope = {"datasetId": "planning-dataset", "clientGeneration": "planning-generation",
                 "accountId": "planning-account", "ledgerId": "owner", "deviceId": "planning-device"}
    common = {"budget_draft_scope": scope, "arrangement_draft_scope": scope, "recurring_draft_scope": scope, "can_write": True, "selected_ledger_id": "owner", "month": "2026-09",
                  "home_currency_code": "JPY", "home_currency_symbol": "¥",
                  "currency_input": currency_input_metadata("JPY"), "currency_options": ["JPY", "CNY", "USD"],
                  "csrf_token": "synthetic", "csrf_field": '<input name="csrf_token" type="hidden" value="synthetic">',
                  "asset_version": "preflight"}
    if kind == "budget":
        common.update(budget=_budget_view(_budget(), currency_code="JPY"),
                      budget_currency_symbol="¥", excluded_category_options=[{"name": "投资", "selected": False}],
                      excluded_categories_other="", save_intent={"home_currency_code": "JPY",
                      "expected_row_version": "1", "idempotency_key": key, "return_category": "餐饮", "return_month": "2026-09"})
        return ENV.get_template("budgets.html").render(**common)
    if kind == "arrangement":
        common.update(income_yuan="1200", fixed_yuan="0", spent_yuan="0", savings_yuan="0",
                      reserved_yuan="0", discretionary_yuan="1200", savings_target_yuan="0",
                      reserved_buffer_yuan="0", run_advise=False, advisor_can_request=True,
                      provider_enabled=False, advice=None, missing_rates=[], expected_row_version="3",
                      idempotency_key=key, arrangement_currency_input=currency_input_metadata("JPY"))
        return ENV.get_template("budget_advise.html").render(**common)
    ctx = listing_context()
    ctx.update(common)
    apply_form_draft(ctx, None, prepare_review=False)
    ctx["items"][0]["current_edit_form"] = None
    ctx["items"][0]["edit_form"].update(merchant="原日元计划", baseline_amount_yuan="1200",
                                       review_required=False, idempotency_key=key)
    return ENV.get_template("recurring.html").render(**ctx)




class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, body, content_type="text/html; charset=utf-8", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/":
            return self.reply('<!doctype html><html><head><meta charset="utf-8"></head><body><script src="/probe.js"></script></body></html>')
        if url.path == "/fixture":
            return self.reply(render(parse_qs(url.query)["kind"][0]))
        if url.path == "/probe.js":
            return self.reply((ROOT / "backend/tests/fixtures/planning_form_draft_refresh_probe.js").read_bytes(), "text/javascript")
        static = (ROOT / "backend/app/static").resolve()
        resource = (static / url.path.removeprefix("/static/")).resolve()
        if url.path.startswith("/static/") and resource.is_relative_to(static) and resource.is_file():
            return self.reply(resource.read_bytes(), "text/javascript")
        if url.path != "/favicon.ico":
            MISSING.append(url.path)
        self.reply("not found", status=404)

    def do_POST(self):
        POSTS.append(self.path)
        self.reply("unexpected write", status=405)


def test_four_planning_entries_retain_original_inputs_and_command_identity_after_refresh(tmp_path: Path) -> None:
    HITS.clear()
    MISSING.clear()
    POSTS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _edge_cdp().evaluate_page(_discover_edge(), profile=tmp_path / "planning-edge",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/", width=1024, height=768,
            expression="window.__planningPreflight || undefined")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    (tmp_path / "planning-refresh-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not MISSING and not POSTS, (MISSING, POSTS)
    assert set(HITS) == {"budget", "arrangement", "recurring-create", "recurring-edit"}
    assert all(row["retained"] for row in result["results"]), result["results"]
