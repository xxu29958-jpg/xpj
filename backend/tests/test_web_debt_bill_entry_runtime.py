"""The Web debt form's original-bill entry, driven in a real browser with the shipped scripts.

The page is the actual ``debt_new.html`` template; a scripted server stands in for the #723 routes,
whose own contract runs on PostgreSQL in ``test_web_debt_bill_capture.py``. Here the browser proves
the frontend half: each key is in the draft before it is sent, a lost upload reply is read back by
its key, a suggestion only completes blanks, and the debt command carries the source reference.
"""
from __future__ import annotations

import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from tests import _web_browser_test_support as browser_runtime

ROOT = Path(__file__).resolve().parents[2]
STATIC = (ROOT / "backend/app/static").resolve()
SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}
CREATION_KEY = "5b3c1961-362f-43a0-b0fa-bdcf06d2d3b9"
ENV = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
        '{% block page_scripts %}{% endblock %}</head><body>{% block content %}{% endblock %}'
        '{% block page_actions %}{% endblock %}<script defer src="/probe.js"></script></body></html>'}),
    FileSystemLoader(ROOT / "backend/app/templates/web"),
]), autoescape=select_autoescape(["html"]))


def _page() -> str:
    return ENV.get_template("debt_new.html").render(
        values={"calendar_revision": "1", "draft_scope": json.dumps(SCOPE), "event_time": "2026-10-30"},
        direction_options=[{"value": "i_owe", "label": "我欠对方"}, {"value": "owed_to_me", "label": "对方欠我"}],
        kind_options=[{"value": "one_off", "label": "一次结清"}, {"value": "revolving", "label": "循环往来"},
            {"value": "installment", "label": "分期还款"}],
        currency_options=["CNY", "JPY"], currency_digits={"CNY": 2, "JPY": 0}, selected_currency_code="CNY",
        form_home_currency_code="CNY", idempotency_key=CREATION_KEY, csrf_token="csrf", selected_ledger_id="owner",
        selected_ledger_name="家庭账本", can_write=True, debtcreation_draft_scope=SCOPE, asset_version="test",
        today="2026-10-30", debtcreation_native_result="", accepted_creation=None, form_error=None, rate_recovery=None)


def _serve(seed: str = ""):
    calls: list[tuple[str, str, dict]] = []
    captures: dict[str, dict] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, payload, kind="application/json", status=200):
            body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            calls.append(("GET", path, {}))
            if path == "/web/debts/new":
                return self.reply(_page().replace("<body>", "<body>" + seed, 1), "text/html; charset=utf-8")
            if path == "/probe.js":
                return self.reply((ROOT / "backend/tests/fixtures/debt_bill_entry_probe.js").read_text(), "text/javascript")
            if path.startswith("/web/debt-bills/by-key/"):
                source = captures.get(path.rsplit("/", 1)[1])
                return self.reply(source, status=200) if source else self.reply({"error": "not_found"}, status=404)
            if path.startswith("/web/debts/"):
                return self.reply("<!doctype html><body><script>window.__debtBillResult = {completed: true};</script></body>",
                    "text/html; charset=utf-8")
            resource = (STATIC / path.removeprefix("/static/")).resolve()
            if path.startswith("/static/") and resource.is_relative_to(STATIC) and resource.is_file():
                kind = "text/css" if resource.suffix == ".css" else "image/svg+xml" if resource.suffix == ".svg" else "text/javascript"
                return self.reply(resource.read_text(), kind)
            return self.reply("not found", "text/plain", 404)

        def fields(self) -> dict:
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            kind = self.headers["Content-Type"]
            if kind.startswith("application/json"):
                return json.loads(raw)
            if kind.startswith("application/x-www-form-urlencoded"):
                return {name: values[0] for name, values in parse_qs(raw.decode(), keep_blank_values=True).items()}
            message = BytesParser(policy=policy.default).parsebytes(f"Content-Type: {kind}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
            return {part.get_param("name", header="content-disposition"):
                part.get_filename() or part.get_payload(decode=True).decode("utf-8") for part in message.iter_parts()}

        def do_POST(self):
            path, values = urlsplit(self.path).path, self.fields()
            calls.append(("POST", path, values))
            if path == "/web/debt-bills":
                captures[values["idempotency_key"]] = {"public_id": "source-1", "creation_key": values["creation_key"],
                    "capture_key": values["idempotency_key"], "row_version": 1, "status": "pending", "file_name": values["file"],
                    "parse_outcome": None, "adopted_debt_public_id": None}
                # Committed, but the reply never arrives.
                return self.reply({"error": "server_error"}, status=503)
            if path == "/web/debt-bills/source-1/parse":
                assert values["expected_row_version"] == 1, values
                return self.reply({"public_id": "source-1", "attempt_key": values["idempotency_key"], "row_version": 2,
                    "status": "succeeded", "provider": "mock", "error_code": None, "completed_at": "2026-10-30T00:00:00Z",
                    "suggestion": {"merchant": "原账单上的出借人", "principal_amount_cents": 120000, "installment_count": 12,
                        "installment_period_months": 1, "source_text": ""}})
            if path == "/web/debts":
                receipt = {"public_id": "debt-1", "ledger_id": "owner", "counterparty_type": "external",
                    "direction": values["direction"], "counterparty_label": values["counterparty_label"].strip(),
                    "home_currency_code": "CNY", "original_currency_code": values["currency_code"], "debt_kind": values["debt_kind"],
                    "installment_count": int(values["installment_count"]), "installment_period_months": int(values["installment_period_months"]),
                    "note": values["note"].strip(), "original_amount_minor": 120000,
                    "accounting_time": {"precision": "date_only", "user_local_date": values["event_time"], "calendar_revision": 1}}
                return self.reply({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
                    "receipt": receipt, "next": "/web/debts/debt-1?ledger_id=owner"})
            return self.reply({"error": "unexpected"}, status=500)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    return server, calls


def _run(tmp_path: Path, seed: str = "", fragment: str = ""):
    server, calls = _serve(seed)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser_runtime._discover_database_browser(),
            profile=tmp_path / "debt-bill-browser", width=393, height=900, result_timeout=20,
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/debts/new?ledger_id=owner{fragment}",
            expression="window.__debtBillResult || undefined", document_url_prefix=f"http://127.0.0.1:{server.server_port}/web/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return result, calls


def test_bill_entry_resumes_a_lost_upload_and_creates_the_debt_with_its_source(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    assert not result.get("error") and result["completed"], result
    uploads = [values for method, path, values in calls if (method, path) == ("POST", "/web/debt-bills")]
    assert len(uploads) == 1 and uploads[0]["creation_key"] == CREATION_KEY, "A lost reply must be read back, not re-sent"
    assert any(path.startswith("/web/debt-bills/by-key/" + uploads[0]["idempotency_key"]) for _, path, _ in calls)
    created = [values for method, path, values in calls if (method, path) == ("POST", "/web/debts")]
    assert len(created) == 1
    body = created[0]
    assert (body["bill_source_public_id"], body["bill_source_row_version"]) == ("source-1", "2")
    assert body["counterparty_label"] == "我自己填的对方" and body["amount_major"] == "1200.00"
    assert not {"bill_capture_key", "bill_parse_key", "bill_discard_key", "bill_file_name"} & set(body), \
        "Draft-only task keys leaked into the debt command"


def test_an_older_draft_without_bill_fields_still_restores(tmp_path: Path) -> None:
    ref = "a33edf9c-93c1-44e7-9164-7758a6fedaaa"
    values = {"ledger_id": "owner", "home_currency_code": "CNY", "currency_code": "CNY", "currency_minor_digits": "2",
        "amount_major": "88.00", "direction": "i_owe", "counterparty_label": "旧原稿里的对方", "event_time": "2026-10-29",
        "calendar_revision": "1", "debt_kind": "one_off", "installment_count": "", "installment_period_months": "", "note": "",
        "amount_placeholder": "输入金额", "amount_inputmode": "decimal"}
    record = {"version": 1, "scope": SCOPE, "clientRef": ref, "phase": "editing", "values": values, "updatedAt": 1}
    seed = ("<script>localStorage.setItem(" + json.dumps("ticketbox:debtcreation-create-draft:v1:" + ref) + ","
        + json.dumps(json.dumps(record, ensure_ascii=False)) + ");window.__legacyDraft = true;</script>")
    result, _ = _run(tmp_path, seed, "#debtcreation-create-" + ref)
    assert not result.get("error") and result["completed"], result
