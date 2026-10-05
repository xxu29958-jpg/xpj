"""Real Web financial input consumers on a synthetic origin; PG owns command correctness."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from typing_extensions import override

_spec = importlib.util.spec_from_file_location("financial_browser_support",
    Path(__file__).with_name("test_web_planning_draft_runtime.py"))
_browser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_browser)

SCOPE = {"datasetId": "fact-dataset", "clientGeneration": "fact-generation", "accountId": "fact-account",
         "ledgerId": "owner", "deviceId": "fact-device"}


def correction_page(prepared=None, native_result="prepared"):
    count = _browser.HITS.get("correction", 0) + 1
    _browser.HITS["correction"] = count
    expense = {"id": 7, "public_id": "fact-seven", "merchant": "原商家" if count == 1 else "后来商家",
        "row_version": count, "original_currency_code": "CNY" if count == 1 else "JPY",
        "original_amount_value": "10.00" if count == 1 else "1500", "category_input": "餐饮", "note": "",
        "tags": "", "expense_time_local": "2026-09-30T12:30", "value_score": 2, "regret_score": None,
        "is_split_received": False}
    item = {"public_id": "item-one", "kind": "product", "name": "原明细", "quantity_text": "1份",
        "unit_price_yuan": "10.00", "amount_yuan": "10.00", "category": "餐饮", "errors": {}}
    split = {"public_id": "split-one", "member_id": "member-one", "amount_yuan": "5.00", "note": "原约定", "errors": {}}
    if prepared:
        expense.update(merchant=prepared["merchant"], original_amount_value=prepared["amount_yuan"],
            original_currency_code=prepared["original_currency"], row_version=prepared["expected_row_version"],
            value_score=prepared["value_score"], regret_score=prepared["regret_score"])
    return _browser.ENV.get_template("expense_correct.html").render(expense=expense, current_expense=expense, can_write=True, correction_mode=True,
        frozen_scalars=[], field_errors={}, csrf_token="synthetic", selected_ledger_id="owner",
        confirm_idempotency_key=prepared["idempotency_key"] if prepared else str(uuid4()),
        reason_input=prepared["reason"] if prepared else "", flow_return_fields={"return_to": "search", "return_query": "原查询"},
        fact_href="/web/expenses/7/edit?ledger_id=owner", currency_options=["CNY", "JPY", "USD"],
        selected_original_currency=expense["original_currency_code"], category_options=["餐饮"],
        currency_input={**_browser.JPY_INPUT, "currency_code": "CNY", "amount_step": "0.01", "inputmode": "decimal"},
        expense_currency_input=_browser.JPY_INPUT, receipt_items={"rows": [item, {**item, "public_id": "", "name": ""}]},
        split_rows={"rows": [split]}, split_members=[{"member_id": "member-one", "account_name": "成员", "role": "member"}],
        fact_draft_scope=SCOPE, fact_draft_client_ref=prepared["draft_client_ref"] if prepared else "",
        fact_draft_result=native_result if prepared else "", asset_version="financial-contract", request={"query_params": {}})


class FinancialHandler(_browser.RecoveryHandler):
    @override
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/web/expenses/7/correct":
            return self.reply(correction_page())
        if path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/financial_fact_draft_probe.js").read_bytes(), "text/javascript")
        return super().do_GET()


class FinancialRecoveryHandler(FinancialHandler):
    @override
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/financial_fact_recovery_probe.js").read_bytes(), "text/javascript")
        if path == "/web/expenses/7/edit":
            return self.reply("<h1>Confirmed current fact</h1>")
        return super().do_GET()

    @override
    def do_POST(self):
        fields = self.read_fields()
        _browser.POSTS.append(fields)
        if len(_browser.POSTS) == 1:
            return self.reply('{"message":"Original reply unavailable"}', "application/json", status=503)
        values = dict(fields)
        return self.reply(json.dumps({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"expense_id": 7, "change_kind": "correction"}, "next": "/web/expenses/7/edit?ledger_id=owner"}), "application/json")


class FinancialReviewHandler(FinancialRecoveryHandler):
    @override
    def do_GET(self):
        if urlsplit(self.path).path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/financial_fact_review_probe.js").read_bytes(), "text/javascript")
        return super().do_GET()

    @override
    def do_POST(self):
        fields = self.read_fields()
        _browser.POSTS.append(fields)
        values = dict(fields)
        if len(_browser.POSTS) == 1:
            return self.reply('{"message":"Peer changed the fact","draft_result":"rejected"}', "application/json", status=409)
        if values.get("review_latest") == "true":
            return self.reply(correction_page({**values, "expected_row_version": "2", "idempotency_key": str(uuid4())}))
        return self.reply(json.dumps({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"expense_id": 7, "change_kind": "correction"}, "next": "/web/expenses/7/edit?ledger_id=owner"}), "application/json")


class FinancialNativeReviewHandler(FinancialReviewHandler):
    @override
    def do_GET(self):
        if urlsplit(self.path).path == "/probe.js":
            probe = (_browser.ROOT / "backend/tests/fixtures/financial_fact_review_probe.js").read_bytes()
            return self.reply(b"window.financialNativeReview = true;\n" + probe, "text/javascript")
        return super().do_GET()

    @override
    def do_POST(self):
        if len(_browser.POSTS) < 2:
            fields = self.read_fields()
            _browser.POSTS.append(fields)
            if len(_browser.POSTS) == 1:
                return self.reply('{"message":"Reply unavailable"}', "application/json", status=503)
            return self.reply(correction_page(dict(fields), native_result="rejected"), status=409)
        return super().do_POST()


def offset_page(expense_id, query):
    key = f"offset-{expense_id}"
    count = _browser.HITS.get(key, 0) + 1
    _browser.HITS[key] = count
    current = count > 1
    code = "JPY" if current else "CNY"
    row = {"public_id": "offset-original", "kind": "refund", "kind_label": "商家退款", "amount_label": "CNY 3.00",
        "accounting_date": "2026-09-30", "reason": "原退回", "row_version": 1, "void_idempotency_key": str(uuid4()), "active": True}
    content = _browser.ENV.from_string("""<div class="fact-workspace">
        <div class="fact-layout" id="fact-overview">{% include '_fact_offsets.html' %}</div>
        {% with reversal=false %}{% include '_offset_form.html' %}{% endwith %}
        {% with reversal=true %}{% include '_offset_form.html' %}{% endwith %}</div>""").render(
        expense={"id": expense_id, "row_version": count, "original_currency_code": code},
        selected_ledger_id="owner", csrf_token="synthetic", edit_return_fields={"return_to": "search", "return_query": "原查询"},
        offset_draft_scope=SCOPE, offset_can_write=True, offset_can_create_refund=not current, offset_can_reverse=not current,
        offset_currency_input=_browser.JPY_INPUT,
        offset_summary={"status": "fully_refunded" if current else "confirmed", "remaining_original_value": "12.00",
            "remaining_original_label": code + " 12.00"}, active_offsets=[row] if expense_id == 12 and not current else [],
        offset_recent_history=[], offset_relationship_impacts={"accepted": []}, offset_void_form={"open": False},
        offset_retained_target={**row, "active": False, "row_version": ""} if current and query.get("continue_offset_id") else None,
        offset_form={"open": False, "kind": "refund", "original_amount": "", "accounting_date": "2026-09-30",
            "reason": "", "expected_row_version": count, "original_currency_code": code, "idempotency_key": str(uuid4())},
        offset_reversal_key=str(uuid4()))
    return '<!doctype html><meta charset="utf-8">' + content + ''.join(
        f'<script src="/static/web/{name}.js" defer></script>' for name in ("desktop/core", "manual-drafts", "plan-entry", "financial-entry"))


class OffsetRecoveryHandler(_browser.RecoveryHandler):
    @override
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/financial_offset_recovery_probe.js").read_bytes(), "text/javascript")
        if url.path.startswith("/web/expenses/") and url.path.endswith("/edit"):
            return self.reply(offset_page(int(url.path.split("/")[3]), parse_qs(url.query)))
        return super().do_GET()

    @override
    def do_POST(self):
        fields = self.read_fields()
        _browser.POSTS.append({"path": self.path, "fields": fields})
        if sum(post["path"] == self.path for post in _browser.POSTS) == 1:
            return self.reply('{"message":"Reply unavailable"}', "application/json", status=503)
        values = dict(fields)
        return self.reply(json.dumps({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["idempotency_key"]},
            "receipt": {"expense_id": int(values["expense_id"]), "change_kind": "offset_void" if values["kind"] == "void" else "offset_create",
                "target_public_id": values["target_public_id"]}, "next": f"/web/expenses/{values['expense_id']}/edit?ledger_id=owner&accepted=1"}), "application/json")


def test_correction_refresh_preserves_raw_inputs_original_basis_and_rows(tmp_path):
    result = _browser._run_browser(tmp_path, FinancialHandler, "window.__financialDraftProbe || undefined")
    (tmp_path / "financial-refresh.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not _browser.POSTS and not _browser.MISSING
    assert result["before"] == result["after"], "Reopening must retain the original intent, currency, version and key"
    assert dict(result["after"])["reason"] == " 原更正依据 "


def test_unknown_correction_replays_exact_original_after_refresh_and_acknowledges_only_that_input(tmp_path):
    result = _browser._run_browser(tmp_path, FinancialRecoveryHandler, "window.__financialRecoveryProbe || undefined")
    (tmp_path / "financial-recovery.json").write_text(json.dumps({"browser": result, "posts": _browser.POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert result["frozen"] and result["reviewHidden"] and result["originalRemoved"]
    assert len(_browser.POSTS) == 2
    assert _browser.POSTS[0] == _browser.POSTS[1]
    posted = dict(_browser.POSTS[0])
    for name in ("original_currency", "amount_yuan", "merchant", "expected_row_version", "value_score", "regret_score", "idempotency_key"):
        assert posted[name] == dict(result["original"])[name], name


def test_explicit_rejected_review_keeps_one_local_input_but_uses_a_new_command_identity(tmp_path):
    result = _browser._run_browser(tmp_path, FinancialReviewHandler, "window.__financialReviewProbe || undefined")
    (tmp_path / "financial-review.json").write_text(json.dumps({"browser": result, "posts": _browser.POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert len(_browser.POSTS) == 3 and result["originalRemoved"]
    original, reviewed, submitted = map(dict, _browser.POSTS)
    assert reviewed["review_latest"] == "true" and reviewed["idempotency_key"] == original["idempotency_key"]
    assert submitted["idempotency_key"] != original["idempotency_key"]
    assert submitted["draft_client_ref"] == original["draft_client_ref"]
    assert original["expected_row_version"] == "1" and submitted["expected_row_version"] == "2"
    for name in ("reason", "merchant", "amount_yuan", "original_currency", "value_score", "regret_score"):
        assert submitted[name] == original[name], name


def test_native_original_result_can_resolve_unknown_before_explicit_review(tmp_path):
    result = _browser._run_browser(tmp_path, FinancialNativeReviewHandler, "window.__financialReviewProbe || undefined")
    assert not result.get("error"), result
    assert len(_browser.POSTS) == 4 and result["originalRemoved"]
    # Native urlencoded and fetch multipart group repeated fields differently.
    # Each field's ordered values, including predecessor IDs, must be identical.
    def columns(fields):
        return {name: [value for key, value in fields if key == name] for name, _ in fields}

    assert columns(_browser.POSTS[0]) == columns(_browser.POSTS[1])
    original, submitted = dict(_browser.POSTS[0]), dict(_browser.POSTS[-1])
    assert submitted["idempotency_key"] != original["idempotency_key"]
    assert submitted["draft_client_ref"] == original["draft_client_ref"]
    assert submitted["reason"] == original["reason"]


def test_refund_reversal_and_disappeared_void_target_replay_original_inputs_after_reload(tmp_path):
    result = _browser._run_browser(tmp_path, OffsetRecoveryHandler, "window.__offsetRecoveryProbe || undefined")
    (tmp_path / "offset-recovery.json").write_text(json.dumps({"browser": result, "posts": _browser.POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert len(result["results"]) == 3 and len(_browser.POSTS) == 6
    for first, replay in zip(_browser.POSTS[::2], _browser.POSTS[1::2], strict=True):
        assert first == replay
    assert all(row["frozen"] and row["removed"] and row["same"] for row in result["results"]), result

