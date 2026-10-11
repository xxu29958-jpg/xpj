"""Paste receipt text through the native Web form and preserve the original command."""

import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from api_contract_helpers import confirm_expense_api, patch_expense
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.models import Expense, LedgerMember, OcrFact
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

pytestmark = pytest.mark.real_db
TEXT = "中国建设银行\n交易金额：18.51\n交易时间：2026年5月4日 16:23:25"


def _open_entry(client, identity):
    created = client.post("/api/expenses/notification-drafts", headers=identity.app_headers,
        json={"source": "alipay", "category": "其他"})
    assert created.status_code == 200, created.text
    expense_id, version = created.json()["id"], created.json()["row_version"]
    action = f"/web/expenses/{expense_id}/recognize-text"
    editor = client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=pending&return_filter=missing_amount")
    assert editor.status_code == 200, editor.text
    assert f'href="{action}?' in editor.text
    assert "粘贴小票文字" in editor.text
    task = client.get(action + "?ledger_id=owner&return_to=pending&return_filter=missing_amount")
    assert task.status_code == 200, task.text
    fields = hidden_post_forms(task.text)[action]
    fields["raw_text"] = TEXT
    assert fields["csrf_token"] and fields["idempotency_key"]
    assert fields["expected_row_version"] == str(version)
    return expense_id, action, fields


def _snapshot(expense_id):
    with SessionLocal() as db:
        row = db.get(Expense, expense_id)
        facts = list(db.scalars(select(OcrFact).where(OcrFact.expense_id == expense_id)))
        return ((row.row_version, row.fact_revision, row.amount_cents, row.merchant, row.category,
                 row.status, row.confirmed_at, row.image_path), len(facts))


def _retained_text(html):
    return unescape(re.search(r'<textarea[^>]*name="raw_text"[^>]*>(.*?)</textarea>', html, re.S).group(1))


def test_text_retry_preserves_command_and_api_replay_does_not_duplicate_suggestion(web_client, identity, monkeypatch):
    expense_id, action, fields = _open_entry(web_client, identity)
    before = _snapshot(expense_id)
    from app.services import expense_ocr_command_service as command
    prepare = command.prepare_pending_expense_fx
    calls = []

    def first_commit_fails(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise SQLAlchemyError("private database fixture")
        return prepare(*args, **kwargs)

    monkeypatch.setattr(command, "prepare_pending_expense_fx", first_commit_fails)
    failed = web_client.post(action, data=fields, follow_redirects=False)
    assert failed.status_code == 503, failed.text
    assert "private database fixture" not in failed.text
    assert _snapshot(expense_id) == before
    assert _retained_text(failed.text) == TEXT
    retry = hidden_post_forms(failed.text)[action]
    retry["raw_text"] = _retained_text(failed.text)
    assert {name: retry[name] for name in fields if name != "csrf_token"} == {
        name: value for name, value in fields.items() if name != "csrf_token"
    }
    accepted = web_client.post(action, data=retry, follow_redirects=False)
    assert accepted.status_code == 303, accepted.text
    query = parse_qs(urlsplit(accepted.headers["location"]).query)
    assert query["ledger_id"] == ["owner"] and query["return_to"] == ["pending"]
    assert query["return_filter"] == ["missing_amount"]
    result, fact_count = _snapshot(expense_id)
    assert (result[0], result[1], result[2], result[5], result[6], fact_count) == (
        before[0][0] + 1, before[0][1], 1851, "pending", None, 1)
    assert result[7] is None, "文字提取不能伪造图片原件"
    replay = web_client.post(f"/api/expenses/{expense_id}/recognize-text",
        headers={**identity.app_headers, "Idempotency-Key": fields["idempotency_key"]},
        json={"expected_row_version": int(fields["expected_row_version"]), "raw_text": TEXT})
    assert replay.status_code == 200, replay.text
    assert _snapshot(expense_id) == (result, fact_count) and len(calls) == 2
    edited = patch_expense(web_client, expense_id, headers=identity.app_headers, fields={"merchant": "人工核对结果"})
    assert edited.status_code == 200, edited.text
    canonical = _snapshot(expense_id)
    assert web_client.post(action, data=fields, follow_redirects=False).status_code == 303
    assert _snapshot(expense_id) == canonical and len(calls) == 2


@pytest.mark.parametrize("change", ["viewer", "manual_edit", "confirmed", "other_ledger"])
def test_text_command_rejects_stale_permission_or_fact_and_preserves_input(web_client, identity, change):
    expense_id, action, fields = _open_entry(web_client, identity)
    if change == "viewer":
        with SessionLocal() as db:
            db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").order_by(LedgerMember.id)).role = "viewer"
            db.commit()
    elif change in {"manual_edit", "confirmed"}:
        edited = patch_expense(web_client, expense_id, headers=identity.app_headers,
            fields={"merchant": "人工核对", "amount_cents": 2345, "expense_time": "2026-05-04T02:00:00Z"})
        assert edited.status_code == 200, edited.text
        if change == "confirmed":
            assert confirm_expense_api(web_client, expense_id, headers=identity.app_headers).status_code == 200
    before = _snapshot(expense_id)
    if change == "other_ledger":
        session = mint_session(web_client, identity=identity)
        with public_client() as browser:
            browser.cookies.set(SESSION_COOKIE_NAME, session, path="/")
            page = browser.get(action + "?ledger_id=owner")
            assert page.status_code == 200, page.text
            fields.update(csrf_token=hidden_post_forms(page.text)[action]["csrf_token"], ledger_id="tester_1")
            response = browser.post(action, data=fields, follow_redirects=False, headers={"Origin": f"https://{PUBLIC_HOST}"})
            retained = hidden_post_forms(response.text)[action]
            assert retained["raw_text"] == TEXT and retained["ledger_id"] == "tester_1"
    else:
        response = web_client.post(action, data=fields, follow_redirects=False)
        assert _retained_text(response.text) == TEXT
    assert response.status_code == {"viewer": 403, "manual_edit": 409, "confirmed": 404, "other_ledger": 409}[change]
    assert _snapshot(expense_id) == before


def test_empty_text_is_correctable_without_new_key(web_client, identity):
    expense_id, action, fields = _open_entry(web_client, identity)
    before = _snapshot(expense_id)
    failed = web_client.post(action, data={**fields, "raw_text": "   "})
    assert failed.status_code == 422 and "1–20000" in failed.text
    assert _retained_text(failed.text) == "   "
    assert hidden_post_forms(failed.text)[action]["idempotency_key"] == fields["idempotency_key"]
    assert _snapshot(expense_id) == before
    corrected = web_client.post(action, data=fields, follow_redirects=False)
    assert corrected.status_code == 303
    assert _snapshot(expense_id)[0][2] == 1851
