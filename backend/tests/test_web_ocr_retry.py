"""Native original-bill OCR retry keeps its intent and never confirms a suggestion."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from api_contract_helpers import confirm_expense_api, patch_expense, upload_png
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal
from app.errors import AppError
from app.models import Expense, LedgerMember, OcrFact
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services.ocr_service import OcrResult
from tests._web_native_form_support import hidden_post_forms
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client

pytestmark = pytest.mark.real_db


def _open_retry(web_client, identity):
    expense_id = upload_png(web_client, identity=identity)
    action = f"/web/expenses/{expense_id}/ocr/retry"
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=pending")
    assert page.status_code == 200, page.text
    forms = hidden_post_forms(page.text)
    assert action in forms, "原单完整页必须提供真实原生识别重试表单"
    fields = forms[action]
    assert fields["ledger_id"] == "owner" and fields["csrf_token"]
    assert fields["return_to"] == "pending"
    assert fields["idempotency_key"] and fields["expected_row_version"]
    assert fields["idempotency_key"] not in {
        forms[f"/web/expenses/{expense_id}/save"]["idempotency_key"],
        forms[f"/web/expenses/{expense_id}/save"]["reject_idempotency_key"],
    }
    return expense_id, action, fields


def _record(expense_id):
    with SessionLocal() as db:
        expense = db.get(Expense, expense_id)
        facts = db.scalars(select(OcrFact).where(OcrFact.expense_id == expense_id)).all()
        return ((expense.status, expense.row_version, expense.fact_revision, expense.amount_cents,
            expense.original_currency_code, expense.original_amount_minor, expense.merchant,
            expense.category, expense.expense_time, expense.confirmed_at), len(facts))


def _suggestion():
    return OcrResult(raw_text="中国建设银行\n交易金额：18.51", confidence=0.9,
        amount_cents=1851, merchant="中国建设银行")


def _accepted_current_page(web_client, response, expense_id, merchant):
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == f"/web/expenses/{expense_id}/edit"
    query = parse_qs(location.query)
    assert query["ledger_id"] == ["owner"] and query["return_to"] == ["pending"]
    current = web_client.get(response.headers["location"])
    assert current.status_code == 200, current.text
    assert "已接受" in current.text and merchant in current.text


def _post_different_ledger_with_session(web_client, identity, expense_id, action, fields):
    session = mint_session(web_client, identity=identity)
    with public_client() as browser:
        browser.cookies.set(SESSION_COOKIE_NAME, session, path="/")
        page = browser.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
        assert page.status_code == 200, page.text
        csrf = hidden_post_forms(page.text)[action]["csrf_token"]
        fields = {**fields, "ledger_id": "tester_1", "csrf_token": csrf}
        response = browser.post(action, data=fields, follow_redirects=False,
            headers={"Origin": f"https://{PUBLIC_HOST}"})
    return response, fields


@pytest.mark.parametrize("failure", ["provider", "queue_busy", "database"])
def test_failed_original_retry_can_resume_same_key_and_occ_then_replay_one_suggestion(
    web_client, monkeypatch, *, identity, failure,
):
    expense_id, action, original = _open_retry(web_client, identity)
    before = _record(expense_id)
    calls = []
    monkeypatch.setattr("app.services.expense_service._ocr._active_provider_name", lambda: "mock")

    def extract(expense):
        calls.append(expense.id)
        if len(calls) == 1 and failure == "provider":
            raise AppError("ocr_unavailable", "识别暂时不可用，请继续原请求。", status_code=503)
        if len(calls) == 1 and failure == "queue_busy":
            raise AppError("rate_limited", "本地大模型识别队列繁忙，请稍后再试。", status_code=429)
        return _suggestion()

    monkeypatch.setattr("app.services.expense_service._ocr.extract_ocr_result", extract)
    if failure == "database":
        from app.services import expense_ocr_command_service as command
        prepare = command.prepare_pending_expense_fx

        def fail_first_staging(*args, **kwargs):
            if len(calls) == 1:
                raise SQLAlchemyError("synthetic database detail must stay private")
            return prepare(*args, **kwargs)
        monkeypatch.setattr(command, "prepare_pending_expense_fx", fail_first_staging)
    failed = web_client.post(action, data=original, follow_redirects=False)
    assert failed.status_code == (429 if failure == "queue_busy" else 503), failed.text
    expected_message = {"provider": "识别暂时不可用", "queue_busy": "识别队列繁忙", "database": "暂时未能取得识别结果"}
    assert expected_message[failure] in failed.text
    assert "synthetic database detail" not in failed.text
    assert _record(expense_id) == before
    retry = hidden_post_forms(failed.text)[action]
    for name in ("ledger_id", "expected_row_version", "idempotency_key", "return_to"):
        assert retry[name] == original[name]
    accepted = web_client.post(action, data=retry, follow_redirects=False)
    _accepted_current_page(web_client, accepted, expense_id, "中国建设银行")
    after, fact_count = _record(expense_id)
    assert fact_count == 1 and after[0] == "pending" and after[-1] is None
    assert after[1] == before[0][1] + 1 and after[3] == 1851
    assert after[2] == before[0][2], "OCR 建议不得创建确认事实修订"
    replay = web_client.post(action, data=original, follow_redirects=False)
    _accepted_current_page(web_client, replay, expense_id, "中国建设银行")
    assert _record(expense_id) == (after, fact_count)
    assert calls == [expense_id, expense_id], "原请求重放不得再次调用 provider 或新增 OCR fact"
    edited = patch_expense(web_client, expense_id, headers=identity.app_headers,
        fields={"merchant": "另一端核对后的现商家", "amount_cents": 2345})
    assert edited.status_code == 200, edited.text
    canonical = _record(expense_id)
    assert canonical[0][1] > after[1] and canonical[0][3] == 2345
    assert canonical[1] == fact_count
    replay_after_edit = web_client.post(action, data=original, follow_redirects=False)
    _accepted_current_page(web_client, replay_after_edit, expense_id, "另一端核对后的现商家")
    assert _record(expense_id) == canonical, "原 OCR 请求重放不得倒退另一端的人工核对事实"
    assert calls == [expense_id, expense_id]


@pytest.mark.parametrize("change", ["viewer", "other_ledger", "manual_edit", "confirmed"])
def test_original_retry_rejects_permission_binding_or_newer_facts_without_writes(
    web_client, monkeypatch, *, identity, change,
):
    expense_id, action, fields = _open_retry(web_client, identity)
    calls = []
    monkeypatch.setattr("app.services.expense_service._ocr._active_provider_name", lambda: "mock")
    monkeypatch.setattr("app.services.expense_service._ocr.extract_ocr_result",
        lambda expense: calls.append(expense.id) or _suggestion())
    if change == "viewer":
        with SessionLocal() as db:
            member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner",
                LedgerMember.disabled_at.is_(None)).order_by(LedgerMember.id))
            member.role = "viewer"
            db.commit()
        page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
        assert page.status_code == 200, page.text
        assert action not in hidden_post_forms(page.text)
    elif change != "other_ledger":
        edited = patch_expense(web_client, expense_id, headers=identity.app_headers, fields={
            "amount_cents": 2345, "merchant": "另一端人工核对", "category": "餐饮",
            "expense_time": datetime(2026, 9, 27, 2, tzinfo=UTC).isoformat(),
        })
        assert edited.status_code == 200, edited.text
        if change == "confirmed":
            confirmed = confirm_expense_api(web_client, expense_id, headers=identity.app_headers)
            assert confirmed.status_code == 200, confirmed.text
    before = _record(expense_id)
    if change == "other_ledger":
        response, fields = _post_different_ledger_with_session(web_client, identity, expense_id, action, fields)
    else:
        response = web_client.post(action, data=fields, follow_redirects=False)
    expected = {"viewer": {403}, "other_ledger": {409}, "manual_edit": {409}, "confirmed": {404}}
    assert response.status_code in expected[change], response.text
    if change == "other_ledger":
        retained = hidden_post_forms(response.text)[action]
        for name in ("ledger_id", "idempotency_key", "expected_row_version"):
            assert retained[name] == fields[name], "绑定冲突必须保留原账本与原提交，不能重绑定到当前会话"
    assert _record(expense_id) == before, "拒绝识别不得改变人工填写、确认事实或 OCR 历史"
    if change in {"viewer", "other_ledger", "confirmed"}:
        assert not calls
