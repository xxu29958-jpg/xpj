"""Actual planning forms retain original raw input after browser refresh; no financial database claim."""
import importlib.util
import json
import threading
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import zip_longest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.services.time_service import to_iso

ROOT = Path(__file__).resolve().parents[2]
_runtime_spec = importlib.util.spec_from_file_location("planning_edge_support", Path(__file__).with_name("test_web_edge_runtime_contract.py"))
_runtime = importlib.util.module_from_spec(_runtime_spec)
_runtime_spec.loader.exec_module(_runtime)

ENV = Environment(loader=ChoiceLoader([
    DictLoader({"base.html": '<!doctype html><html><head><meta charset="utf-8">'
                '<script src="/static/web/desktop/core.js" defer></script>'
                '{% block page_scripts %}{% endblock %}</head><body>'
                '{% block content %}{% endblock %}</body></html>'}),
    FileSystemLoader(ROOT / "backend/app/templates/web"),
]), autoescape=select_autoescape(["html"]))
ENV.filters["to_iso"] = to_iso
HITS = {}
MISSING = []
POSTS = []
JPY_INPUT = {"currency_code": "JPY", "currency_symbol": "¥", "amount_step": "1", "inputmode": "numeric",
             "amount_placeholder": "0", "amount_example": "1200", "positive_amount_min": "1", "amount_input_hint": "整数"}


def _rule_definition(kind, common, scope, key):
    editing = kind == "rule-edit"
    draft = {"ledger_id": "owner", "rule_id": "41" if editing else "", "keyword": "原规则", "category": "餐饮",
        "priority": "10", "home_currency_code": "JPY" if HITS[kind] == 1 else "CNY", "amount_min_yuan": "1200",
        "amount_max_yuan": "", "source_contains": "", "tag_contains": "", "expected_row_version": str(HITS[kind]),
        "draft_scope": json.dumps(scope), "draft_ref": str(uuid4()), "idempotency_key": key,
        "return_category": "", "return_month": ""}
    return ENV.get_template("rule_definition.html").render(**common, rule_draft=draft, rule_id=41 if editing else None,
        rule_draft_scope=scope, rule_currency_input=JPY_INPUT, definition_available=True, definition_result="", q="?ledger_id=owner")


def _recurring_definition(kind, common, key, values, native_result):
    if kind == "occurrence":
        return _occurrence_definition(common, common["recurring_draft_scope"], key, HITS[kind])
    if kind == "candidate":
        common.update(review={"merchant": "原日元订阅", "amount_cents": "1200", "home_currency_code": "JPY",
            "amount_yuan": "1200", "occurrence_count": 3, "next_expected_date": "2026-10-09",
            "idempotency_key": key, **(values or {})}, history_month="2026-09", recurring_draft_result=native_result)
        return ENV.get_template("recurring.html").render(**common)
    common.update(items=[{"public_id": "series-one", "merchant": "原日元计划", "merchant_editable": True,
        "status": "active", "source": "manual", "home_currency_code": "JPY", "row_version": 7,
        "edit_form": {"merchant": "原日元计划", "baseline_amount_yuan": "1200", "home_currency_code": "JPY",
            "expected_row_version": "7", "idempotency_key": key, "next_expected_date": "2026-05-09", "currency_input": JPY_INPUT}}],
        create_form={"merchant": "", "baseline_amount_yuan": "", "home_currency_code": "JPY",
            "idempotency_key": uuid4().hex, "next_expected_date": "2026-06-08", "currency_input": JPY_INPUT})
    common.update(recurring_creation=kind == "recurring-create", open_edit_id="series-one" if kind == "recurring-edit" else "")
    if values:
        common["items"][0]["edit_form"].update(values)
        common.update(draft_public_id="series-one", recurring_draft_result=native_result)
    return ENV.get_template("recurring.html").render(**common)


def _occurrence_definition(common, scope, key, version):
    draft = {"ledger_id": "owner", "public_id": "series-one", "task_id": "series-one:2026-09",
        "month": "2026-09", "payment_month": "2026-08", "q": "原付款", "payment_id": "41",
        "action": "clear" if version == 1 else "", "expense_public_id": "", "expected_expense_row_version": "",
        "expected_row_version": str(version), "expected_series_row_version": "7",
        "series_label": "原日元订阅", "payment_label": "跨月付款 · JPY 2400",
        "idempotency_key": key, "draft_scope": json.dumps(scope), "original_only": version > 1}
    return ENV.get_template("recurring_occurrence.html").render(**common,
        item={"public_id": "series-one", "merchant_name": "原日元订阅", "status": "active"},
        occurrence={"period": "2026-09", "state": "unfulfilled", "row_version": version, "home_currency_code": "JPY"},
        planned_amount="2400", reserved_amount="2400", payment_month="2026-08", query="原付款",
        command_draft=draft, command_draft_scope=scope, command_result="", command_binding_required=False,
        undo_draft_scope=scope, can_associate=True, payments=[], occurrence_href="/web/recurring/series-one/occurrence?ledger_id=owner")


def _rate_definition(kind, common, scope, key):
    version = 2 if HITS[kind] == 1 else 9
    task = {"ledger_id": "owner", "month": "2026-09", "home_currency_code": "CNY", "return_to": "reports",
        "granularity": "week", "ranking_metric": "count", "merchant_category": "旅行"}
    values = {**task, "currency_code": "JPY", "rate_date": "2026-09-09", "rate_to_cny": "0.05",
        "expected_row_version": str(version), "idempotency_key": key, "draft_scope": json.dumps(scope)}
    target = "/web/reports?" + urlencode({name: value for name, value in task.items() if name != "return_to"})
    return ENV.get_template("budget_rates.html").render(**common, values=values, rate_task=task, rates=[],
        rate_draft_scope=scope, currency_codes=["CNY", "JPY"], return_href=target, return_label="期间报表")


def _debt_definition(kind, common, scope, key):
    task = kind.removeprefix("debt-")
    public_id = "original-debt-goal" if task != "create" else ""
    choices = [{"public_id": identity, "name": "原欠款" + identity, "meta": "未结清", "status_label": "未结清", "status": "open"}
        for identity in (["debt-a", "debt-b"] if HITS[kind] == 1 else ["debt-b"])]
    goal = {"name": "原还债目标", "is_archived": False, "eval_label": "进行中", "links": []} if public_id else None
    values = {"ledger_id": "owner", "name": "原还债目标" if public_id else "", "debt_public_ids": [],
        "expected_row_version": "4" if HITS[kind] == 1 else "9", "idempotency_key": key, "target_date": "2030-12-31"}
    return ENV.get_template("debt_goal_entry.html").render(**common, task=task, goal=goal, values=values, choices=choices,
        public_id=public_id, task_id=f"{public_id}:{task}" if public_id else "", debtgoal_draft_scope=scope,
        draft_result="", binding_required=False, entry_title="还债目标", entry_button="保存目标",
        entry_action="/web/debt-goals/" + (f"{public_id}/{task}" if public_id else "create"),
        entry_href="/web/debt-goals/" + (f"{public_id}/{task}" if public_id else "new"), return_href="/web/debt-goals?ledger_id=owner")


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
    renderer = {"rate": _rate_definition, "rule-create": _rule_definition, "rule-edit": _rule_definition,
        "debt-create": _debt_definition, "debt-links": _debt_definition, "debt-target-date": _debt_definition}.get(kind)
    if renderer:
        return renderer(kind, common, scope, key)
    if kind.startswith("catalog-"):
        command = kind.removeprefix("catalog-")
        item = {"public_id": "merchant-original", "display_name": "原商家", "status": "active", "row_version": 7}
        command_form = {"ledger_id": "owner", "merchant": item["public_id"], "search": "原筛选", "status": "all",
            "source_name": item["display_name"], "target_name": "", "expected_row_version": "7", "display_name": "原商家",
            "next_status": "hidden", "target": "", "alias_policy": "", "idempotency_key": key,
            "draft_ref": str(uuid4()), "draft_scope": json.dumps(scope)}
        return ENV.get_template("merchants.html").render(**common, merchant_draft_scope=scope,
            merchant_view="command", command_kind=command, command_form=command_form, command_result="", command_error="",
            command_available=True, command_label="确认商家操作", selected_merchant=item, catalog=[item,
                {"public_id": "merchant-target", "display_name": "原目标", "status": "active", "row_version": HITS[kind]}],
            directory_href="/web/merchants?ledger_id=owner", q="?ledger_id=owner")
    if kind in {"merchant-create", "alias-create"}:
        creation = {"ledger_id": "owner", "search": "原筛选", "status": "all", "merchant": "",
            "display_name": "", "canonical_merchant": "", "alias": "", "draft_scope": json.dumps(scope), "idempotency_key": key}
        return ENV.get_template("merchants.html").render(**common, merchant_draft_scope=scope,
            catalog_form=creation, alias_form=creation, merchant_view="new" if kind == "merchant-create" else "aliases",
            catalog=[], aliases=[], visible_aliases=[], merge_draft={}, alias_create_draft={},
            directory_href="/web/merchants?ledger_id=owner", q="?ledger_id=owner", creation_result="", creation_kind="")
    if kind in {"tag-create", "category-create"}:
        reference_kind = kind.removesuffix("-create")
        return ENV.get_template("reference_create.html").render(**common, kind=reference_kind,
            label="标签" if reference_kind == "tag" else "分类", reference_draft_scope=scope,
            values={"ledger_id": "owner", "name": "", "month": "2026-09", "unused": "1",
                "idempotency_key": key, "draft_scope": json.dumps(scope)}, draft_result="", error="",
            return_href="/web/library?ledger_id=owner")
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
    return _recurring_definition(kind, common, key, values, native_result)




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


def _merchant_receipt(path, values, result):
    result["receipt"].update(row_version=1, display_name=values.get("display_name"), canonical_merchant=values.get("canonical_merchant"))
    result["next"] = "/web/merchants?ledger_id=owner"
    if values.get("merchant"):
        result["receipt"].update(public_id=values["merchant"], row_version=int(values["expected_row_version"]) + 1,
            status=values.get("next_status", "active"), deleted_at="2026-10-08T00:00:00Z" if path.endswith("/delete") else None)
    if path.endswith("/merge"):
        target, version = values["target"].rsplit(":", 1)
        result["receipt"].update(status="merged", merged_into_public_id=target)
        result["receipt"] = {"source": result["receipt"], "target": {"public_id": target, "row_version": int(version) + 1},
            "created_alias_public_id": "original-alias" if values["alias_policy"] == "create_source_alias" else None}


def _planning_receipt(path, values, result):
    if path.startswith("/web/debt-goals/"):
        result["receipt"]["goal_type"] = "debt_repayment"
        result["next"] = "/web/debt-goals?ledger_id=owner"
    if path == "/web/budget-advise/rates":
        result["receipt"].update(**{name: values[name] for name in ("currency_code", "home_currency_code", "rate_date", "rate_to_cny")},
            row_version=int(values["expected_row_version"]) + 1)
        result["next"] = "/web/reports?" + urlencode({name: values[name] for name in
            ("ledger_id", "month", "home_currency_code", "granularity", "ranking_metric", "merchant_category")})
    if path == "/web/recurring/confirm-candidate":
        result["receipt"].update(source="candidate", status="active", row_version=1,
            home_currency_code=values["home_currency_code"], baseline_amount_cents=int(values["amount_cents"]),
            next_expected_date=values["next_expected_date"] or None)
    if path.endswith("/occurrence"):
        result["receipt"].update(series_public_id=values["public_id"], period=values["month"],
            row_version=int(values["expected_row_version"]) + 1,
            expense_public_id=None if values["action"] == "clear" else values["expense_public_id"])
        result["next"] = path + "?ledger_id=owner&month=" + values["month"]


class RecoveryHandler(Handler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/probe.js":
            return self.reply((ROOT / "backend/tests/fixtures/planning_form_draft_recovery_probe.js").read_bytes(), "text/javascript")
        if path == "/web/budget-advise/rates":
            return self.reply(render("rate"))
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
        if self.path.startswith("/web/reference/"):
            destination = "/web/tags" if values["kind"] == "tag" else "/web/categories"
        result = {"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"public_id": values.get("public_id") or "00000000-0000-0000-0000-000000000001",
                "kind": values.get("kind"), "month": values.get("month"), "row_version": 8},
            "next": destination + "?ledger_id=owner"}
        if self.path.startswith("/web/rules/"):
            result["receipt"] = {"id": int(values["rule_id"] or "43"), "row_version": int(values["expected_row_version"]) + 1 if values["rule_id"] else 1,
                "keyword": values["keyword"].strip(), "category": values["category"].strip()}
            result["next"] = "/web/rules?ledger_id=owner"
        _planning_receipt(self.path, values, result)
        if self.path.startswith("/web/merchants/"):
            _merchant_receipt(self.path, values, result)
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


class RecurringReviewHandler(RecoveryHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/probe.js":
            return self.reply((ROOT / "backend/tests/fixtures/planning_recurring_review_probe.js").read_bytes(), "text/javascript")
        return super().do_GET()

    def do_POST(self):
        fields = self.read_fields()
        values = dict(fields)
        POSTS.append({"path": self.path, "fields": fields})
        candidate = self.path == "/web/recurring/confirm-candidate"
        if values.get("review_latest") == "true":
            return self.reply(render("candidate" if candidate else "recurring-edit", {**values, "expected_row_version": "8",
                "prepared_from_key": values["idempotency_key"], "idempotency_key": str(uuid4())}, "prepared"))
        if len(POSTS) == 1:
            return self.reply('{"message":"Another client changed this plan","draft_result":"rejected"}',
                "application/json", status=409)
        result = {"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"public_id": "series-one", "row_version": 9}, "next": "/web/recurring?ledger_id=owner"}
        if candidate:
            result["receipt"].update(source="candidate", status="active", row_version=1,
                home_currency_code=values["home_currency_code"], baseline_amount_cents=int(values["amount_cents"]),
                next_expected_date=values["next_expected_date"] or None)
        return self.reply(json.dumps(result), "application/json")


def _run_browser(tmp_path, handler, expression, query=""):
    HITS.clear()
    MISSING.clear()
    POSTS.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return _runtime._edge_cdp().evaluate_page(_runtime._discover_edge(), profile=tmp_path / "planning-edge",
            prepare_url=lambda _: f"http://127.0.0.1:{server.server_port}/{query}", width=1024, height=768,
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
    for row in result["results"]:
        differences = [(before, after) for before, after in zip_longest(row["before"], row["after"]) if before != after]
        assert row["retained"], (row["entry"], differences)


@pytest.mark.parametrize("group", ["planning", "debt"])
def test_planning_and_reference_entries_replay_original_body_after_unknown_reply_and_reload(tmp_path: Path, group: str):
    result = _run_browser(tmp_path, RecoveryHandler, "window.__planningRecovery || undefined", "?group=" + group)
    (tmp_path / "planning-recovery-result.json").write_text(json.dumps({"browser": result, "posts": POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not MISSING, MISSING
    expected = {"debt-create", "debt-links", "debt-target-date"} if group == "debt" else {
        "budget", "arrangement", "rate", "recurring-create", "recurring-edit", "candidate", "occurrence", "tag-create", "category-create",
        "merchant-create", "alias-create", "catalog-rename", "catalog-toggle", "catalog-delete", "catalog-merge", "rule-create", "rule-edit"}
    assert {row["entry"] for row in result["results"]} == expected
    assert len(POSTS) == 2 * len(result["results"])
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


@pytest.mark.parametrize("kind", ["recurring-edit", "candidate"])
def test_recurring_review_replaces_only_the_rejected_draft_before_explicit_save(tmp_path: Path, kind: str):
    result = _run_browser(tmp_path, RecurringReviewHandler, "window.__recurringReview || undefined", "?kind=" + kind)
    assert not result.get("error"), result
    assert not MISSING and len(POSTS) == 3
    rejected, review, accepted = [dict(post["fields"]) for post in POSTS]
    assert rejected["idempotency_key"] == review["idempotency_key"] == result["original"]
    assert accepted["idempotency_key"] == result["replacement"] != result["original"]
    if kind == "recurring-edit":
        assert rejected["expected_row_version"] == "7" and accepted["expected_row_version"] == "8"
        assert all(fields["baseline_amount_yuan"] == "2500" for fields in (rejected, review, accepted))
    else:
        assert all(fields["amount_cents"] == "1200" and fields["next_expected_date"] == ""
            for fields in (rejected, review, accepted))
    assert all(fields["home_currency_code"] == "JPY" for fields in (rejected, review, accepted))
    assert result["replacementRetainedBeforeSave"] and result["confirmed"] and result["unrelatedRetained"]
