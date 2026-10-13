"""The actual CSV consumer must recover an unknown command beside a completed row."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from typing_extensions import override

from tests.test_web_import_event_review import BATCH, root, row

_spec = importlib.util.spec_from_file_location("csv_browser_support",
    Path(__file__).with_name("test_web_planning_draft_runtime.py"))
_browser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_browser)
PATH = f"/web/import/{BATCH}/rows/3/review"
SCOPE = {"datasetId": "csv-dataset", "clientGeneration": "csv-generation", "accountId": "csv-member",
         "ledgerId": "family", "deviceId": "csv-browser"}


def review_page():
    from app.routes._web_money_views import _minor_amount_label

    resumed = bool(_browser.POSTS)
    return _browser.ENV.get_template("import_event_review.html").render(
        can_write=True, csrf_token="fixture", selected_ledger_id="family", asset_version="test",
        public_id=BATCH, row=row(status="applied" if resumed else "review", resolved_expense_id=42),
        root=vars(root(row_version=10 if resumed else 9)), row_amount_label=_minor_amount_label,
        draft={"expense_id": "42", "expected_row_version": "10" if resumed else "9", "reason": "",
               "acknowledge_incomplete_lineage": "", "manual_exchange_rate": "", "exchange_rate_date": "",
               "draft_scope": json.dumps(SCOPE), "draft_client_ref": str(uuid4())},
        review_path=PATH, batch_href=f"/web/import/{BATCH}?ledger_id=family",
        root_edit_href="/web/expenses/42/edit?ledger_id=family", import_draft_scope=SCOPE,
        import_binding_required=False, source_file_name="events.csv", event_net_preview=None)


class CsvReviewHandler(_browser.RecoveryHandler):
    @override
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == PATH:
            return self.reply(review_page())
        if path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/csv_review_recovery_probe.js").read_bytes(), "text/javascript")
        return super().do_GET()

    @override
    def do_POST(self):
        fields = self.read_fields()
        _browser.POSTS.append(fields)
        if len(_browser.POSTS) == 1:
            return self.reply('{"message":"Original reply unavailable"}', "application/json", status=503)
        values = dict(fields)
        return self.reply(json.dumps({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": values["draft_client_ref"]},
            "receipt": {"public_id": BATCH, "line_number": 3, "status": "matched", "expense_id": 42},
            "next": f"{PATH}?ledger_id=family"}), "application/json")


def test_unknown_csv_review_replays_original_after_completed_row_refresh(tmp_path):
    result = _browser._run_browser(tmp_path, CsvReviewHandler, "window.__csvRecovery || undefined")
    (tmp_path / "csv-recovery.json").write_text(json.dumps({"browser": result, "posts": _browser.POSTS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    assert not result.get("error"), result
    assert not _browser.MISSING
    assert result["frozen"] and result["reviewHidden"] and result["originalRemoved"]
    assert len(_browser.POSTS) == 2 and _browser.POSTS[0] == _browser.POSTS[1]
    fields = dict(_browser.POSTS[1])
    assert fields["expense_id"] == "42" and fields["expected_row_version"] == "9"
    assert fields["reason"] == "原退款说明" and json.loads(fields["draft_scope"]) == SCOPE
