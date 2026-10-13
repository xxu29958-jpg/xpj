"""Web subtasks keep original rows, commands and receipts across real consumers."""
import json
import re
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiIdempotencyKey, Expense, ExpenseRevision
from app.routes import _web_expense_helpers, web_expense_edit, web_expense_items, web_expense_splits
from tests import test_expense_subtask_receipts as receipt_tests
from tests import test_web_expense_fact_items_ack as fact_ack_tests
from tests import test_web_expense_review_runtime as review_tests

confirmation_store = review_tests.confirmation_store
confirmation_web = review_tests.confirmation_web
review_browser = review_tests.review_browser
subtask_store = receipt_tests.subtask_store
fact_review_browser = review_tests.fact_review_browser
_PRESENTERS = {name: getattr(_web_expense_helpers, name)
    for name in ("_web_item_rows", "web_split_rows", "web_split_members")}


@pytest.fixture
def subtask_browser(review_browser, subtask_store, confirmation_web, monkeypatch):
    client, scope = review_browser
    _, options = confirmation_web
    for name, presenter in _PRESENTERS.items():
        monkeypatch.setattr(_web_expense_helpers, name, presenter)
    for module in (web_expense_items, web_expense_splits):
        client.app.include_router(module.router)
        monkeypatch.setattr(module, "_list_ledger_options", lambda db: options)
        monkeypatch.setattr(module, "_resolve_selected_ledger_id", lambda *a, **kw: "owner")

    def local(request: web_expense_edit.Request):
        request.state.web_session_auth = SimpleNamespace(ledger_id="owner", account_id=11, device_id=None)

    client.app.dependency_overrides[web_expense_edit.LocalOnly.dependency] = local
    return client, scope, options, subtask_store


def _original(kind, scope, version):
    fields = {"ledger_id": "owner", "expected_row_version": str(version), "idempotency_key": str(uuid4()),
        "draft_ref": str(uuid4()), "draft_scope": json.dumps(scope), "return_to": "pending", "return_filter": "ready"}
    if kind == "items":
        fields.update(item_name=["原明细"], item_kind=["product"], item_quantity=[""],
            item_unit_price_yuan=[""], item_amount_yuan=["5.00"], item_category=["购物"])
    elif kind == "splits":
        fields.update(split_member_id=["1"], split_amount_yuan=["5.00"], split_note=["原家庭分摊"])
    return fields


@pytest.fixture
def subtask_journey(subtask_browser, fact_review_browser):
    client, _, options, engine = subtask_browser

    @client.app.get("/subtask-probe.js")
    def probe():
        return FileResponse(Path(__file__).parent / "fixtures/expense_subtask_recovery_probe.js", media_type="text/javascript")

    @client.app.post("/web/subtask-probe/peer/{kind}")
    def peer(kind: str):
        with Session(engine) as db:
            current = db.get(Expense, 42)
            if kind == "ack":
                current.status = "confirmed"
                current.row_version += 1
                db.commit()
            else:
                receipt_tests._submit(db, "items", current.row_version, "later-peer", label="后来明细", amount=700)
            return {"row_version": db.get(Expense, 42).row_version}

    @client.app.post("/web/subtask-probe/role/{role}")
    def role(role: str):
        options[0].role = role
        return {"role": role}

    client.app.state.expense_review_probe = "subtask-probe.js"
    return client, engine


@pytest.mark.parametrize("scenario", ["rows", "ack", "fact-ack"])
def test_real_web_subtasks_resume_originals_without_overwriting_other_work(subtask_journey, tmp_path, scenario):
    client, engine = subtask_journey
    if scenario.endswith("ack"):
        with Session(engine) as db:
            receipt_tests._prepare(db, "ack")
            if scenario == "fact-ack":
                current = db.get(Expense, 42)
                current.status, current.confirmed_at = "confirmed", current.created_at
                db.commit()
    result = review_tests._run_review_page(client, tmp_path,
        f"/web/expenses/42/edit?ledger_id=owner&return_to=pending&return_filter=ready&probe={scenario}")
    assert not result.get("error"), json.dumps(result, ensure_ascii=False)
    assert result["requests"][0]["body"] == result["requests"][1]["body"]
    assert result["receipts"][0] == result["receipts"][1]
    with Session(engine) as db:
        current = db.get(Expense, 42)
        assert (current.merchant, current.amount_cents) == ("首次便利店", 12860)
        if scenario == "rows":
            assert result["raw_restored"] and result["current_separate"] and result["readonly_retained"]
            assert result["other_original_preserved"] and result["reviewed_new_key"] and result["shelf"]
            assert receipt_tests._facts(db)[:6] == ("pending", 7, 12860, "mismatch_known",
                [("后来明细", 700)], [(1, 550, "原拆账填写")])
        else:
            assert result["ack_recovered_after_confirmation"]
            assert (current.status, current.row_version, current.items_sum_status) == ("confirmed", 7, "mismatch_acknowledged")
            if scenario == "fact-ack":
                assert db.scalars(select(ExpenseRevision.change_kind).where(ExpenseRevision.expense_id == 42)).all().count("correction") == 1


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_web_subtask_replay_retains_first_result_after_confirmation_and_revocation(subtask_browser, kind):
    client, scope, options, engine = subtask_browser
    with Session(engine) as db:
        version = receipt_tests._prepare(db, kind)
    original = _original(kind, scope, version)
    path = f"/web/expenses/42/{kind}/save" if kind != "ack" else "/web/expenses/42/items/acknowledge-mismatch"
    headers = {"Accept": "application/json"}
    first = client.post(path, data=original, headers=headers, follow_redirects=False)
    assert first.status_code == 200 and first.headers["content-type"].startswith("application/json"), first.text
    accepted = first.json()
    assert accepted["ack"] == {"scope": scope, "clientRef": original["idempotency_key"]}
    assert accepted["receipt"]["row_version"] == version + 1
    with Session(engine) as db:
        peer = db.get(Expense, 42)
        peer.status, peer.row_version, peer.merchant = "confirmed", version + 2, "后来人工事实"
        db.commit()
        facts = receipt_tests._facts(db)
    options[0].role = "viewer"
    denied = client.post(path, data=original, headers=headers, follow_redirects=False)
    assert denied.status_code == 403 and denied.json()["draft_result"] == "blocked"
    options[0].role = "owner"
    replay = client.post(path, data=original, headers=headers, follow_redirects=False)
    assert replay.status_code == 200 and replay.json() == accepted
    with Session(engine) as db:
        assert receipt_tests._facts(db) == facts
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == original["idempotency_key"])).response_body == accepted["receipt"]


def test_native_fact_acknowledgement_keeps_rejected_original_until_explicit_review(subtask_journey):
    client, engine = subtask_journey
    with Session(engine) as db:
        version = receipt_tests._prepare(db, "ack")
        current = db.get(Expense, 42)
        current.status, current.confirmed_at = "confirmed", current.created_at
        db.commit()
        before = receipt_tests._facts(db)
    page = client.get("/web/expenses/42/edit?ledger_id=owner")
    native = fact_ack_tests._ack_form_html(page.text, 42)
    original = {name: unescape(fact_ack_tests._hidden_value(native, name))
        for name in ("ledger_id", "expected_row_version", "idempotency_key", "draft_ref", "draft_scope")}
    original["expected_row_version"] = str(version - 1)
    path = "/web/expenses/42/items/acknowledge-mismatch"
    rejected = client.post(path, data=original)
    assert rejected.status_code == 409 and "账单详情" in rejected.text
    native = fact_ack_tests._ack_form_html(rejected.text, 42)
    assert fact_ack_tests._hidden_value(native, "expected_row_version") == str(version - 1)
    assert fact_ack_tests._hidden_value(native, "idempotency_key") == original["idempotency_key"]
    review = re.search(r"<button[^>]*data-expenseack-review[^>]*>", native).group()
    assert "hidden" not in review and "disabled" not in review
    prepared = client.post(path, data={**original, "review_latest": "true"})
    assert prepared.status_code == 200
    native = fact_ack_tests._ack_form_html(prepared.text, 42)
    updated = {name: unescape(fact_ack_tests._hidden_value(native, name))
        for name in ("expected_row_version", "idempotency_key", "draft_ref", "draft_scope")}
    assert updated["idempotency_key"] != original["idempotency_key"]
    assert updated["draft_ref"] == original["draft_ref"] and updated["expected_row_version"] == str(version)
    with Session(engine) as db:
        assert receipt_tests._facts(db) == before
    accepted = client.post(path, data={**original, **updated}, follow_redirects=False)
    assert accepted.status_code == 303
    with Session(engine) as db:
        current = db.get(Expense, 42)
        assert (current.status, current.row_version, current.items_sum_status) == ("confirmed", version + 1, "mismatch_acknowledged")
