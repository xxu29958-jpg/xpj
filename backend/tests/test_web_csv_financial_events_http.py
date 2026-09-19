"""Native CSV review through actual Web forms on the PostgreSQL lane."""

import csv
import re
from html import unescape
from io import StringIO
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import LedgerMember
from tests._web_native_form_support import accounting_time_fields, hidden_post_forms
from tests.expense_correction_support import idem, manual_confirmed
from tests.test_csv_financial_events_http import _bundle, _export, _fact_counts, _foreign_source_export, _rows
from tests.test_expense_offset_lifecycle import _create_refund
from tests.test_web_import_review_native_forms import _apply_native_csv, _preview_native_csv


def _post(browser, page, action, fields):
    return browser.post(action, data=fields,
        headers={"Origin": str(browser.base_url).rstrip("/"), "Referer": str(page.url)}, follow_redirects=False)


def _confirm_visible_root(browser, review, expense_id):
    links = [unescape(href) for href in re.findall(r'href="([^"]+)"', review.text)]
    edit_href, = [href for href in links if urlsplit(href).path == f"/web/expenses/{expense_id}/edit"]
    edit = browser.get(edit_href)
    assert edit.status_code == 200, edit.text
    form = hidden_post_forms(edit.text)[f"/web/expenses/{expense_id}/save"]
    # Submit the displayed scalar values, as the native save-and-confirm button does.
    for name in ("amount_yuan", "merchant", "category", "tags"):
        match = re.search(rf'name="{name}"\s+value="([^"]*)"', edit.text)
        assert match is not None, (name, edit.text)
        form[name] = unescape(match.group(1))
    form.update(accounting_time_fields(edit.text))
    note = re.search(r'<textarea\b[^>]*name="note"[^>]*>(.*?)</textarea>', edit.text, re.DOTALL)
    form["note"] = unescape(note.group(1)) if note else ""
    confirmed = _post(browser, edit, f"/web/expenses/{expense_id}/confirm", form)
    assert confirmed.status_code == 303, confirmed.text
    target = urlsplit(confirmed.headers["location"])
    assert target.path == urlsplit(str(review.url)).path
    assert parse_qs(target.query)["expense_id"] == [str(expense_id)]
    return browser.get(confirmed.headers["location"])


def test_foreign_web_csv_resume_confirm_occ_retry_csrf_and_viewer(web_client, identity):
    content, source = _foreign_source_export(web_client, identity)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53131)) as browser:
        batch, detail_url = _preview_native_csv(browser, ledger_id="tester_1", csv_text=content.decode("utf-8-sig"))
        _apply_native_csv(browser, public_id=batch, ledger_id="tester_1", batch_size=10)
        saved = _rows(web_client, identity.gray_app_headers, batch)
        purchase, = [item for item in saved["items"] if item["entry_kind"] == "expense"]
        refund, = [item for item in saved["items"] if item["entry_kind"] == "offset"]
        expense_id = purchase["expense_id"]
        action = f"/web/import/{batch}/rows/{refund['line_number']}/review"
        detail = browser.get(detail_url)
        assert action in detail.text and "新消费草稿" in detail.text and "待复核" in detail.text
        review = browser.get(action, params={"ledger_id": "tester_1"})
        assert review.status_code == 200 and "复核并确认原单，完成后返回" in review.text
        resumed = _confirm_visible_root(browser, review, expense_id)
        assert resumed.status_code == 200 and "确认原单并登记退款" in resumed.text
        fields = {**hidden_post_forms(resumed.text)[action], "reason": "保留这次退款说明 <核对>"}
        assert fields["expense_id"] == str(expense_id)
        before = _fact_counts("tester_1")

        no_csrf = {key: value for key, value in fields.items() if key != "csrf_token"}
        denied = _post(browser, resumed, action, no_csrf)
        assert denied.status_code == 403, denied.text
        assert _fact_counts("tester_1") == before

        changed = web_client.post(f"/api/expenses/{expense_id}/corrections", headers=idem(identity.gray_app_headers),
            json={"expected_row_version": int(fields["expected_row_version"]), "reason": "另一端补充备注", "note": "补充后的说明"})
        assert changed.status_code == 201, changed.text
        conflict = _post(browser, resumed, action, fields)
        assert conflict.status_code == 409, conflict.text
        assert "保留这次退款说明 &lt;核对&gt;" in conflict.text
        assert "已载入最新原单和版本" in conflict.text
        retry = {**hidden_post_forms(conflict.text)[action], "reason": fields["reason"]}
        assert int(retry["expected_row_version"]) > int(fields["expected_row_version"])
        accepted = _post(browser, conflict, action, retry)
        assert accepted.status_code == 303, accepted.text
        result = browser.get(accepted.headers["location"])
        assert result.status_code == 200 and "此退款已入账" in result.text
        assert action not in hidden_post_forms(result.text)
        actual = _bundle(web_client, identity.gray_app_headers, expense_id)
        offset, = actual["active_offsets"]
        assert offset["amount_cents"] == source["active_offsets"][0]["amount_cents"]
        assert offset["exchange_rate_date"] == "2026-05-05" and offset["category"] == "售后"
        after = _fact_counts("tester_1")
        assert _post(browser, result, action, retry).status_code == 303
        assert _fact_counts("tester_1") == after

        hub = browser.get("/web/import?ledger_id=tester_1")
        assert batch in hub.text and "事件入账 1" in hub.text
        with SessionLocal() as db:
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "tester_1").limit(1))
            member.role = "viewer"
            db.commit()
        readonly = browser.get(str(result.url))
        assert readonly.status_code == 200 and action not in hidden_post_forms(readonly.text)
        assert _post(browser, readonly, action, retry).status_code == 403
        assert _fact_counts("tester_1") == after


def test_orphan_web_refund_selects_pending_root_and_returns_with_that_selection(web_client, identity):
    source_root = manual_confirmed(web_client, identity, amount_cents=10000)
    _create_refund(web_client, identity, source_root)
    exported = csv.DictReader(StringIO(_export(web_client, identity.app_headers).decode("utf-8-sig")))
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=exported.fieldnames)
    writer.writeheader()
    writer.writerows(item for item in exported if item["entry_kind"] == "offset")
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 53132)) as browser:
        refund_batch, _ = _preview_native_csv(browser, ledger_id="tester_1", csv_text=output.getvalue())
        _apply_native_csv(browser, public_id=refund_batch, ledger_id="tester_1")
        refund, = _rows(web_client, identity.gray_app_headers, refund_batch)["items"]
        action = f"/web/import/{refund_batch}/rows/{refund['line_number']}/review"
        missing = browser.get(action, params={"ledger_id": "tester_1"})
        assert missing.status_code == 200 and "补充上传原单" in missing.text
        other_ledger = browser.get(action, params={"ledger_id": "tester_1", "expense_id": source_root["id"]})
        assert "确认原单并登记退款" not in other_ledger.text

        root_batch, _ = _preview_native_csv(browser, ledger_id="tester_1",
            csv_text="amount_yuan,merchant,category\n100.00,需要明确选择的原消费,餐饮\n")
        _apply_native_csv(browser, public_id=root_batch, ledger_id="tester_1")
        target_root, = _rows(web_client, identity.gray_app_headers, root_batch)["items"]
        expense_id = target_root["expense_id"]
        search = browser.get(action, params={"ledger_id": "tester_1", "query": "需要明确选择"})
        assert "选择此原单" in search.text and f'name="expense_id" value="{expense_id}"' in search.text
        selected = browser.get(action, params={"ledger_id": "tester_1", "expense_id": expense_id})
        assert "本次选择的原单" in selected.text
        resumed = _confirm_visible_root(browser, selected, expense_id)
        fields = {**hidden_post_forms(resumed.text)[action], "reason": "核对金额日期，明确关联这笔原消费"}
        assert fields["expense_id"] == str(expense_id)
        accepted = _post(browser, resumed, action, fields)
        assert accepted.status_code == 303, accepted.text
        assert _rows(web_client, identity.gray_app_headers, refund_batch)["items"][0]["resolved_expense_id"] == expense_id
        assert len(_bundle(web_client, identity.gray_app_headers, expense_id)["active_offsets"]) == 1
