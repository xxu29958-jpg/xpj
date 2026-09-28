"""Actual planning forms retain original raw input after browser refresh; no financial database claim."""
import importlib.util
import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[2]
_runtime_spec = importlib.util.spec_from_file_location("planning_edge_support", Path(__file__).with_name("test_web_edge_runtime_contract.py"))
_runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(_runtime)

ENV = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
                '{% block page_scripts %}{% endblock %}</head><body>'
                '{% block content %}{% endblock %}</body></html>'}),
    FileSystemLoader(ROOT / "backend/app/templates/web"),
]), autoescape=select_autoescape(["html"]))
HITS = {}
MISSING = []
POSTS = []
JPY_INPUT = {"currency_code": "JPY", "currency_symbol": "¥", "amount_step": "1", "inputmode": "numeric",
             "amount_placeholder": "0", "amount_example": "1200", "positive_amount_min": "1", "amount_input_hint": "整数"}


def render(kind, values=None, native_result=""):
    HITS[kind] = HITS.get(kind, 0) + 1
    key = str(uuid4())
    scope = {"datasetId": "planning-dataset", "clientGeneration": "planning-generation",
                 "accountId": "planning-account", "ledgerId": "owner", "deviceId": "planning-device"}
    common = {"budget_draft_scope": scope, "arrangement_draft_scope": scope, "recurring_draft_scope": scope, "can_write": True, "selected_ledger_id": "owner", "month": "2026-09",
                  "home_currency_code": "JPY", "home_currency_symbol": "¥",
                  "currency_input": JPY_INPUT, "currency_options": ["JPY", "CNY", "USD"],
                  "csrf_token": "synthetic", "csrf_field": '<input name="csrf_token" type="hidden" value="synthetic">',
                  "asset_version": "preflight", "request": {"query_params": {}}, "status_filter": ""}
    if kind == "budget":
        common.update(budget={"configured": True, "home_currency_code": "JPY", "form_total_yuan": "1200",
                      "form_rollover_yuan": "0", "form_non_monthly_yuan": "0", "spent_yuan": "100", "remaining_yuan": "1100",
                      "category_rows": [{"is_configured": True, "index": 0, "category": "餐饮", "saved_category": "餐饮",
                          "amount_yuan": "1200", "spent_yuan": "100", "remaining_yuan": "1100"},
                          {"is_configured": False, "category": "", "amount_yuan": ""},
                          {"is_configured": False, "category": "", "amount_yuan": ""}]},
                      budget_currency_symbol="¥", excluded_category_options=[{"name": name, "selected": False}
                          for name in (["投资", "医疗"] if HITS[kind] % 2 else ["医疗", "投资"])],
                      excluded_categories_other="", save_intent={"home_currency_code": "JPY",
                      "expected_row_version": "1", "idempotency_key": key, "return_category": "餐饮", "return_month": "2026-09"})
        if HITS[kind] > 1:
            common["save_intent"].update(home_currency_code="CNY", expected_row_version="2")
            common["currency_input"] = {**JPY_INPUT, "currency_code": "CNY", "amount_step": "0.01", "inputmode": "decimal"}
        return ENV.get_template("budgets.html").render(**common)
    if kind == "arrangement":
        common.update(income_yuan="1200", fixed_yuan="0", spent_yuan="0", savings_yuan="0",
                      reserved_yuan="0", discretionary_yuan="1200", savings_target_yuan="0",
                      reserved_buffer_yuan="0", run_advise=False, advisor_can_request=True,
                      provider_enabled=False, advice=None, missing_rates=[], expected_row_version="3",
                      idempotency_key=key, arrangement_currency_input=JPY_INPUT)
        if HITS[kind] > 1:
            common.update(home_currency_code="USD", expected_row_version="4", arrangement_currency_input={**JPY_INPUT, "currency_code": "CNY"})
        if values:
            common.update({name: values[name] for name in ["month", "home_currency_code", "expected_row_version",
                "idempotency_key", "draft_scope", "savings_target_yuan", "reserved_buffer_yuan"]})
            common["arrangement_draft_result"] = native_result
            common["arrangement_currency_input"] = JPY_INPUT
        return ENV.get_template("budget_advise.html").render(**common)
    common.update(items=[{"public_id": "series-one", "merchant": "原日元计划", "merchant_editable": True,
        "status": "active", "source": "manual", "home_currency_code": "JPY", "row_version": 7,
        "edit_form": {"merchant": "原日元计划", "baseline_amount_yuan": "1200", "home_currency_code": "JPY",
            "expected_row_version": "7", "idempotency_key": key, "next_expected_date": "2026-05-09", "currency_input": JPY_INPUT}}],
        create_form={"merchant": "", "baseline_amount_yuan": "", "home_currency_code": "JPY",
            "idempotency_key": uuid4().hex, "next_expected_date": "2026-06-08", "currency_input": JPY_INPUT})
    return ENV.get_template("recurring.html").render(**common)




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


class RecoveryHandler(Handler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/probe.js":
            return self.reply((ROOT / "backend/tests/fixtures/planning_form_draft_recovery_probe.js").read_bytes(), "text/javascript")
        if path.startswith("/web/"):
            return self.reply('<!doctype html><html><body data-confirmed>原提交已确认</body></html>')
        return super().do_GET()

    def read_fields(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if self.headers["Content-Type"].startswith("application/x-www-form-urlencoded"):
            return [(name, value) for name, values in parse_qs(raw.decode(), keep_blank_values=True).items() for value in values]
        message = BytesParser(policy=policy.default).parsebytes(
            f'Content-Type: {self.headers["Content-Type"]}\r\nMIME-Version: 1.0\r\n\r\n'.encode() + raw)
        return [(part.get_param("name", header="content-disposition"), part.get_payload(decode=True).decode("utf-8"))
            for part in message.iter_parts()]

    def do_POST(self):
        fields = self.read_fields()
        POSTS.append({"path": self.path, "fields": fields})
        count = sum(post["path"] == self.path for post in POSTS)
        if count == 1:
            return self.reply('{"message":"Original receipt unavailable"}', "application/json", status=503)
        values = dict(fields)
        destination = "/web/recurring" if self.path.startswith("/web/recurring") else self.path.removesuffix("/save")
        result = {"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"public_id": values.get("public_id") or "synthetic-series", "month": values.get("month"), "row_version": 8},
            "next": destination + "?ledger_id=owner"}
        return self.reply(json.dumps(result), "application/json")


class ArrangementReviewHandler(RecoveryHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/probe.js":
            return self.reply((ROOT / "backend/tests/fixtures/planning_arrangement_review_probe.js").read_bytes(), "text/javascript")
        return super().do_GET()

    def do_POST(self):
        fields = self.read_fields()
        values = dict(fields)
        POSTS.append({"path": self.path, "fields": fields})
        if self.path == "/web/budget-advise":
            return self.reply(render("arrangement", values))
        if values.get("review_latest") == "true":
            return self.reply(render("arrangement", {**values, "expected_row_version": "4"}, "prepared"))
        if len(POSTS) == 2:
            return self.reply('{"message":"Another client changed this arrangement","draft_result":"rejected"}',
                "application/json", status=409)
        result = {"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"month": values["month"], "row_version": 5}, "next": "/web/budget-advise?ledger_id=owner"}
        return self.reply(json.dumps(result), "application/json")


def _run_browser(tmp_path, handler, expression):
    HITS.clear()
    MISSING.clear()
    POSTS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return _runtime._edge_cdp().evaluate_page(_runtime._discover_edge(), profile=tmp_path / "planning-edge",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/", width=1024, height=768,
            expression=expression)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_four_planning_entries_retain_original_inputs_and_command_identity_after_refresh(tmp_path: Path) -> None:
    result = _run_browser(tmp_path, Handler, "window.__planningPreflight || undefined")
    (tmp_path / "planning-refresh-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not MISSING and not POSTS, (MISSING, POSTS)
    assert set(HITS) == {"budget", "arrangement", "recurring-create", "recurring-edit"}
    assert all(row["retained"] for row in result["results"]), result["results"]


def test_four_planning_entries_replay_original_body_after_unknown_reply_and_reload(tmp_path: Path):
    result = _run_browser(tmp_path, RecoveryHandler, "window.__planningRecovery || undefined")
    (tmp_path / "planning-recovery-result.json").write_text(json.dumps({"browser": result, "posts": POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not MISSING, MISSING
    assert len(POSTS) == 8 and len(result["results"]) == 4
    for first, replay in zip(POSTS[::2], POSTS[1::2], strict=True):
        assert first == replay, "Retry must retain repeated fields, original scope, currency, month, version and key"
    assert all(row["confirmed"] and row["originalRemoved"] and row["frozen"] for row in result["results"]), result


def test_arrangement_preview_and_explicit_rejected_review_leave_financial_save_explicit(tmp_path: Path):
    result = _run_browser(tmp_path, ArrangementReviewHandler, "window.__planningReview || undefined")
    (tmp_path / "planning-review-result.json").write_text(json.dumps({"browser": result, "posts": POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not MISSING and len(POSTS) == 4
    trial, refused, review, accepted = [dict(post["fields"]) for post in POSTS]
    assert POSTS[0]["path"] == "/web/budget-advise" and "review_latest" not in trial
    assert review["review_latest"] == "true" and "review_latest" not in accepted
    assert refused["expected_row_version"] == "3" and accepted["expected_row_version"] == "4"
    for fields in [trial, refused, review, accepted]:
        assert fields["idempotency_key"] == result["ref"] and fields["savings_target_yuan"] == "001200"
        assert fields["reserved_buffer_yuan"] == "00030" and fields["arrangement_currency_code"] == "JPY"
    assert result["confirmed"] and result["originalRemoved"]
