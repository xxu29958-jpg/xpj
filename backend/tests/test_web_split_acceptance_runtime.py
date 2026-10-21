"""Production invitation forms retain original acceptance; owner correctness lives in PG tests."""
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from typing_extensions import override

_spec = importlib.util.spec_from_file_location("split_accept_browser", Path(__file__).with_name("test_web_planning_draft_runtime.py"))
_browser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_browser)
SCOPE = {"datasetId": "split-dataset", "clientGeneration": "split-generation", "accountId": "receiver",
         "ledgerId": "viewer-book", "deviceId": "original-browser"}
PUBLIC_ID = "1206c596-f80f-4edf-b0b8-e8eff3968437"


def invitation_page(path, query):
    accepted = bool(_browser.POSTS)
    focused = path.endswith("/accept")
    row = {"public_id": PUBLIC_ID, "status": "accepted" if accepted else "invited", "share_label": "JPY ¥1,200",
        "source_amount_label": "JPY ¥5,000", "source_date_label": "2026-01-31", "sender_display_name": "家人甲",
        "merchant": "一起聚餐", "is_expired": False, "expires_at": datetime(2030, 1, 1, tzinfo=UTC), "events": [],
        "amount_cents": "1200", "home_currency_code": "JPY", "draft_ref": str(uuid4()),
        "accept_choices": [{"ledger_id": "private", "name": "个人账本"}, {"ledger_id": "travel", "name": "出差账本"}]}
    if focused and accepted:
        row["accept_choices"] = [{"ledger_id": "private", "name": "个人账本"}]
    scope = {**SCOPE, "deviceId": "replacement-browser"} if "changed" in query else SCOPE
    return _browser.ENV.get_template("bill_splits_inbox.html").render(bill_split_rows=[row] if focused or not accepted else [],
        split_inbox_status="invited", splitaccept_draft_scope=scope, csrf_token="synthetic", can_write=False,
        selected_ledger_id=SCOPE["ledgerId"], asset_version="acceptance-test", accept_task=focused,
        splitaccept_original_only=query.get("original_only") == ["true"], receipt=None, flash_message="", flash_type="")


class AcceptanceHandler(_browser.RecoveryHandler):
    @override
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/probe.js":
            return self.reply((_browser.ROOT / "backend/tests/fixtures/split_acceptance_recovery_probe.js").read_bytes(), "text/javascript")
        if url.path.startswith("/web/bill-splits/"):
            return self.reply(invitation_page(url.path, parse_qs(url.query)))
        return super().do_GET()

    @override
    def do_POST(self):
        values = dict(self.read_fields())
        _browser.POSTS.append(values)
        if len(_browser.POSTS) == 1:
            return self.reply('{"message":"Saved, but original reply lost"}', "application/json", status=503)
        receipt = {"public_id": PUBLIC_ID, "status": "accepted", "amount_cents": 1200,
            "home_currency_code": "JPY", "target_ledger_id": "private" if len(_browser.POSTS) == 2 else "travel"}
        return self.reply(json.dumps({"ack": {"scope": json.loads(values["draft_scope"]), "clientRef": PUBLIC_ID},
            "receipt": receipt, "next": "/web/bill-splits/inbox?ledger_id=viewer-book&accepted=" + PUBLIC_ID}), "application/json")


def test_original_target_survives_refresh_lost_reply_terminal_history_and_missing_target(tmp_path):
    result = _browser._run_browser(tmp_path, AcceptanceHandler, "window.__splitAcceptanceRecovery || undefined")
    assert not result.get("error"), result
    assert result["selectedAfterReload"] == "travel", result
    assert result["scopeBlocked"] and result["originalRemoved"] and result["wrongReceiptRetained"], result
    assert result["restoredName"] == "出差账本", result
    assert not _browser.MISSING and len(_browser.POSTS) == 3, (_browser.MISSING, _browser.POSTS)
    assert _browser.POSTS[0] == _browser.POSTS[1] == _browser.POSTS[2]
    assert _browser.POSTS[0]["target_ledger_id"] == "travel"
    assert json.loads(_browser.POSTS[0]["draft_scope"]) == SCOPE
