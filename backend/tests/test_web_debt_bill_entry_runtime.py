"""The Web debt form's original-bill entry, driven in a real browser with the shipped scripts.

The page is the actual ``debt_new.html`` template; a scripted server stands in for the #723 routes,
whose own contract runs on PostgreSQL in ``test_web_debt_bill_capture.py``. Here the browser proves
the frontend half: each key is in the draft before it is sent, the debt command waits until the
chosen bill is settled, a lost reply is read back by its key, and a suggestion only completes blanks.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from tests import _web_browser_test_support as browser_runtime

ROOT = Path(__file__).resolve().parents[2]
STATIC = (ROOT / "backend/app/static").resolve()
SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account", "ledgerId": "owner", "deviceId": "browser"}
CREATION_KEY = "5b3c1961-362f-43a0-b0fa-bdcf06d2d3b9"
SOURCE = {"public_id": "source-1", "row_version": 1, "status": "pending", "parse_outcome": None, "adopted_debt_public_id": None}
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


class BillServer:
    """The #723 routes as the browser sees them, with one scripted fault per scenario."""

    def __init__(self, scenario: str, seed: str):
        self.scenario, self.seed = scenario, seed
        self.calls: list[tuple[str, str, dict]] = []
        self.captures: dict[str, dict] = {}
        self.read_backs = 0
        self.parse_requests = 0

    def get(self, path: str):
        if path == "/web/debts/new":
            return 200, "text/html; charset=utf-8", _page().replace("<body>", "<body>" + self.seed, 1)
        if path == "/probe.js":
            return 200, "text/javascript", (ROOT / "backend/tests/fixtures/debt_bill_entry_probe.js").read_text()
        if path.startswith("/web/debt-bills/by-key/"):
            return self.read_back(path.rsplit("/", 1)[1])
        if path == "/web/debt-bills/source-1":
            return self.restored_source()
        if path.startswith("/web/debts/"):
            return 200, "text/html; charset=utf-8", "<!doctype html><body><script>window.__debtBillResult = {completed: true};</script></body>"
        resource = (STATIC / path.removeprefix("/static/")).resolve()
        if path.startswith("/static/") and resource.is_relative_to(STATIC) and resource.is_file():
            kind = "text/css" if resource.suffix == ".css" else "image/svg+xml" if resource.suffix == ".svg" else "text/javascript"
            return 200, kind, resource.read_text()
        return 404, "text/plain", "not found"

    def restored_source(self):
        if self.scenario not in {"parse-replay", "parse-replay-unknown"}:
            return 200, "application/json", {**SOURCE, "row_version": 2, "file_name": "借条.png"}
        # Slow enough that the restore and the following editability update both ask to recover.
        time.sleep(0.4)
        return 200, "application/json", {**SOURCE, "file_name": "借条.png"}

    def read_back(self, key: str):
        self.read_backs += 1
        if self.scenario == "lost" and self.read_backs == 1:
            return 503, "application/json", {"error": "server_error"}
        source = self.captures.get(key)
        return (200, "application/json", source) if source else (404, "application/json", {"error": "not_found"})

    def post(self, path: str, values: dict):
        if path == "/web/debt-bills":
            return self.capture(values)
        if path == "/web/debt-bills/source-1/parse":
            self.parse_requests += 1
            if self.scenario == "parse-replay-unknown" and self.parse_requests == 1:
                return 503, "application/json", {"error": "server_error"}  # An outcome is not yet readable.
            return 200, "application/json", self.parse(values)
        if path == "/web/debts":
            return 200, "application/json", self.create(values)
        return 500, "application/json", {"error": "unexpected"}

    def capture(self, values: dict):
        if self.scenario == "delayed":
            time.sleep(1.5)
        self.captures[values["idempotency_key"]] = {**SOURCE, "creation_key": values["creation_key"],
            "capture_key": values["idempotency_key"], "file_name": values["file"]}
        if self.scenario == "lost":
            return 503, "application/json", {"error": "server_error"}  # Committed; the reply never arrives.
        return 200, "application/json", self.captures[values["idempotency_key"]]

    def parse(self, values: dict) -> dict:
        assert values["expected_row_version"] == 1, values
        if self.scenario in {"parse-replay", "parse-replay-unknown"}:
            time.sleep(0.8)  # A model call: long enough for a second recovery to overlap it.
        outcome = {"public_id": "source-1", "attempt_key": values["idempotency_key"], "row_version": 2, "provider": "mock",
            "completed_at": "2026-10-30T00:00:00Z", "status": "succeeded", "error_code": None,
            "suggestion": {"merchant": "原账单上的出借人", "principal_amount_cents": 120000, "installment_count": 12,
                "installment_period_months": 1, "source_text": ""}}
        if self.scenario == "parse-failed":
            outcome.update(status="failed", error_code="provider_unavailable", suggestion=None)
        return outcome

    def create(self, values: dict) -> dict:
        count = int(values["installment_count"]) if values["installment_count"] else None
        receipt = {"public_id": "debt-1", "ledger_id": "owner", "counterparty_type": "external",
            "direction": values["direction"], "counterparty_label": values["counterparty_label"].strip(),
            "home_currency_code": "CNY", "original_currency_code": values["currency_code"], "debt_kind": values["debt_kind"],
            "installment_count": count, "installment_period_months": int(values["installment_period_months"]) if count else None,
            "note": values["note"].strip(), "original_amount_minor": int(values["amount_major"].replace(".", "")),
            "accounting_time": {"precision": "date_only", "user_local_date": values["event_time"], "calendar_revision": 1}}
        return {"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": receipt, "next": "/web/debts/debt-1?ledger_id=owner"}


def _fields(headers, raw: bytes) -> dict:
    kind = headers["Content-Type"]
    if kind.startswith("application/json"):
        return json.loads(raw)
    if kind.startswith("application/x-www-form-urlencoded"):
        return {name: values[0] for name, values in parse_qs(raw.decode(), keep_blank_values=True).items()}
    message = BytesParser(policy=policy.default).parsebytes(f"Content-Type: {kind}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
    return {part.get_param("name", header="content-disposition"):
        part.get_filename() or part.get_payload(decode=True).decode("utf-8") for part in message.iter_parts()}


def _handler(bills: BillServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, kind, payload):
            body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # The page may move on (e.g. to the created debt) before a late read finishes.
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            bills.calls.append(("GET", path, {}))
            self.reply(*bills.get(path))

        def do_POST(self):
            path = urlsplit(self.path).path
            values = _fields(self.headers, self.rfile.read(int(self.headers["Content-Length"])))
            bills.calls.append(("POST", path, values))
            self.reply(*bills.post(path, values))

    return Handler


def _run(tmp_path: Path, scenario: str, seed: str = "", fragment: str = ""):
    bills = BillServer(scenario, '<script>window.__scenario = "' + scenario + '";</script>' + seed)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(bills))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = browser_runtime._edge_cdp().evaluate_page(browser_runtime._discover_database_browser(),
            profile=tmp_path / "debt-bill-browser", width=393, height=900, result_timeout=30,
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/web/debts/new?ledger_id=owner{fragment}",
            expression="window.__debtBillResult || undefined", document_url_prefix=f"http://127.0.0.1:{server.server_port}/web/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return result, bills


def _posts(bills: BillServer, path: str) -> list[dict]:
    return [values for method, call, values in bills.calls if (method, call) == ("POST", path)]


@pytest.mark.parametrize("scenario", ["currency-capture", "currency-parse"])
def test_currency_changes_preserve_the_active_bill_operation(tmp_path: Path, scenario: str) -> None:
    result, bills = _run(tmp_path, scenario)
    assert not result.get("error") and result["completed"], result
    assert len(_posts(bills, "/web/debt-bills")) == len(_posts(bills, "/web/debt-bills/source-1/parse")) == 1
    assert bills.read_backs == 0, "An active upload is not recovered before its reply arrives"
    created = _posts(bills, "/web/debts")
    assert len(created) == 1
    assert (created[0]["bill_source_public_id"], created[0]["bill_source_row_version"], created[0]["idempotency_key"]) == \
        ("source-1", "2", CREATION_KEY)
    assert (created[0]["currency_code"], created[0]["amount_major"], created[0]["counterparty_label"]) == \
        ("CNY", "66.00", "切换币种保留的对方")


def test_a_parse_result_not_retained_can_be_explicitly_recovered(tmp_path: Path) -> None:
    result, bills = _run(tmp_path, "parse-storage")
    assert not result.get("error") and result["completed"], result
    parses = _posts(bills, "/web/debt-bills/source-1/parse")
    assert len(parses) == 2 and parses[0] == parses[1], "Explicit recovery keeps the original attempt and version"
    created = _posts(bills, "/web/debts")
    assert len(created) == len(_posts(bills, "/web/debt-bills")) == 1
    assert (created[0]["bill_source_public_id"], created[0]["bill_source_row_version"], created[0]["amount_major"]) == \
        ("source-1", "2", "66.00")


@pytest.mark.parametrize("scenario", ["delayed", "lost", "storage", "storage-release", "parse-failed", "revolving"])
def test_the_debt_command_waits_for_the_chosen_bill_and_carries_it_once(tmp_path: Path, scenario: str) -> None:
    result, bills = _run(tmp_path, scenario)
    assert not result.get("error") and result["completed"], result
    uploads, created = _posts(bills, "/web/debt-bills"), _posts(bills, "/web/debts")
    assert len(uploads) == 1 and uploads[0]["creation_key"] == CREATION_KEY, "A bill is uploaded once under this debt's key"
    assert len(created) == 1, "Exactly one debt is created"
    body = created[0]
    assert (body["bill_source_public_id"], body["bill_source_row_version"]) == ("source-1", "2")
    assert body["counterparty_label"] == "我自己填的对方"
    assert body["amount_major"] == ("66.00" if scenario == "parse-failed" else "1200.00")
    if scenario == "revolving":
        assert (body["debt_kind"], body["installment_count"], body["installment_period_months"]) == ("revolving", "", ""), \
            "An installment suggestion must not turn a chosen revolving debt into an invalid installment pair"
    assert not {"bill_capture_key", "bill_parse_key", "bill_discard_key", "bill_file_name"} & set(body), \
        "Draft-only task keys leaked into the debt command"
    if scenario in {"lost", "storage", "storage-release"}:
        assert bills.read_backs >= (2 if scenario == "lost" else 1), "The original was read back by its key, not re-sent"


def test_an_older_draft_without_bill_fields_still_restores(tmp_path: Path) -> None:
    ref = "a33edf9c-93c1-44e7-9164-7758a6fedaaa"
    values = {"ledger_id": "owner", "home_currency_code": "CNY", "currency_code": "CNY", "currency_minor_digits": "2",
        "amount_major": "88.00", "direction": "i_owe", "counterparty_label": "旧原稿里的对方", "event_time": "2026-10-29",
        "calendar_revision": "1", "debt_kind": "one_off", "installment_count": "", "installment_period_months": "", "note": "",
        "amount_placeholder": "输入金额", "amount_inputmode": "decimal"}
    record = {"version": 1, "scope": SCOPE, "clientRef": ref, "phase": "editing", "values": values, "updatedAt": 1}
    seed = ("<script>localStorage.setItem(" + json.dumps("ticketbox:debtcreation-create-draft:v1:" + ref) + ","
        + json.dumps(json.dumps(record, ensure_ascii=False)) + ");window.__legacyDraft = true;</script>")
    result, _ = _run(tmp_path, "legacy", seed, "#debtcreation-create-" + ref)
    assert not result.get("error") and result["completed"], result


def test_a_draft_holding_a_source_beside_its_resolved_capture_key_is_released(tmp_path: Path) -> None:
    ref = "c79fc5f1-9c08-46a4-b2c6-712bc130e8f5"
    values = {"ledger_id": "owner", "home_currency_code": "CNY", "currency_code": "CNY", "currency_minor_digits": "2",
        "amount_major": "37.76", "direction": "i_owe", "counterparty_label": "旧键原稿", "event_time": "2026-10-30",
        "calendar_revision": "1", "debt_kind": "one_off", "installment_count": "", "installment_period_months": "", "note": "",
        "bill_source_public_id": "source-1", "bill_source_row_version": "2", "bill_capture_key": "4f9a7c1e-0d2b-4c6a-9e1f-3b5d7a9c2e40",
        "bill_parse_key": "", "bill_discard_key": "", "bill_file_name": "借条.png",
        "amount_placeholder": "输入金额", "amount_inputmode": "decimal"}
    record = {"version": 1, "scope": SCOPE, "clientRef": ref, "phase": "editing", "values": values, "updatedAt": 1}
    seed = ("<script>localStorage.setItem(" + json.dumps("ticketbox:debtcreation-create-draft:v1:" + ref) + ","
        + json.dumps(json.dumps(record, ensure_ascii=False)) + ");window.__staleKeyDraft = true;</script>")
    result, bills = _run(tmp_path, "stale-key", seed, "#debtcreation-create-" + ref)
    assert not result.get("error") and result["completed"], result
    created = _posts(bills, "/web/debts")
    assert len(created) == 1 and not _posts(bills, "/web/debt-bills"), "A known source is neither re-uploaded nor held"
    assert (created[0]["bill_source_public_id"], created[0]["bill_source_row_version"], created[0]["idempotency_key"]) == \
        ("source-1", "2", ref)


@pytest.mark.parametrize("scenario", ["parse-replay", "parse-replay-unknown"])
def test_reopening_a_draft_replays_its_unanswered_parse_attempt_once(tmp_path: Path, scenario: str) -> None:
    ref, attempt = "7d1c2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f", "9e8d7c6b-5a49-4382-a716-152433425160"
    values = {"ledger_id": "owner", "home_currency_code": "CNY", "currency_code": "CNY", "currency_minor_digits": "2",
        "amount_major": "", "direction": "i_owe", "counterparty_label": "等识别的原稿", "event_time": "2026-10-30",
        "calendar_revision": "1", "debt_kind": "one_off", "installment_count": "", "installment_period_months": "", "note": "",
        "bill_source_public_id": "source-1", "bill_source_row_version": "1", "bill_capture_key": "", "bill_parse_key": attempt,
        "bill_discard_key": "", "bill_file_name": "借条.png", "amount_placeholder": "输入金额", "amount_inputmode": "decimal"}
    record = {"version": 1, "scope": SCOPE, "clientRef": ref, "phase": "editing", "values": values, "updatedAt": 1}
    seed = ("<script>localStorage.setItem(" + json.dumps("ticketbox:debtcreation-create-draft:v1:" + ref) + ","
        + json.dumps(json.dumps(record, ensure_ascii=False)) + ");window.__parseReplayDraft = true;</script>")
    result, bills = _run(tmp_path, scenario, seed, "#debtcreation-create-" + ref)
    assert not result.get("error") and result["completed"], {"browser": result, "parse_requests": bills.parse_requests}
    parses = _posts(bills, "/web/debt-bills/source-1/parse")
    expected_attempts = [attempt] * (2 if scenario == "parse-replay-unknown" else 1)
    assert [values["idempotency_key"] for values in parses] == expected_attempts, "Recovery and an explicit retry retain the original attempt"
    created = _posts(bills, "/web/debts")
    assert len(created) == 1 and (created[0]["bill_source_row_version"], created[0]["amount_major"]) == ("2", "1200.00")
