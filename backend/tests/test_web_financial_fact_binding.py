"""Installed browser identity, original receipts and authoritative financial postconditions."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Expense, ExpenseOffsetFact, ExpenseOffsetRevision, ExpenseRevision, LedgerMember
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._runtime_protocol import current_protocol_headers
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_correction_fx_continuation import _read_form
from tests.test_web_expense_offsets import _money_fields
from tests.web_expense_fact_test_support import create_confirmed

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture
def installed():
    yield from installed_web_setup()


def test_bound_correction_offset_and_void_replay_without_rewriting_later_facts(installed):
    token = _connect_local_session(installed)
    client = installed.browser
    client.base_url = client.base_url.copy_with(scheme="https")
    api_headers = current_protocol_headers({"Authorization": f"Bearer {token}"})
    identity = SimpleNamespace(app_headers=api_headers)
    expense_id = create_confirmed(client, identity=identity)
    origin = {"Origin": str(client.base_url).rstrip("/"), "Accept": "application/json"}
    editor = client.get(f"/web/expenses/{expense_id}/correct", params={
        "ledger_id": installed.shared_ledger_id, "return_to": "search", "return_query": "原查询"})
    assert editor.status_code == 200, editor.text
    correction = _read_form(editor, expense_id)
    correction.set("merchant", "浏览器更正")
    correction.set("reason", "原更正原因")
    accepted = client.post(correction.action, data=correction.fields, headers=origin)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["ack"] == {"scope": json.loads(correction.one("draft_scope")),
        "clientRef": correction.one("idempotency_key")}
    with SessionLocal() as db:
        fact = db.get(Expense, expense_id)
        version = fact.row_version
    later = client.post(f"/api/expenses/{expense_id}/corrections",
        headers={**api_headers, "Idempotency-Key": str(uuid4())},
        json={"reason": "另一端核对", "merchant": "后来人工修改", "expected_row_version": version})
    assert later.status_code == 201, later.text
    replay = client.post(correction.action, data=correction.fields, headers=origin)
    assert replay.status_code == 200 and replay.json() == accepted.json()
    wrong_scope = json.loads(correction.one("draft_scope"))
    wrong_scope["deviceId"] = "another-browser"
    refused = client.post(correction.action, data={**correction.fields, "draft_scope": json.dumps(wrong_scope)}, headers=origin)
    assert refused.status_code == 409 and refused.json()["draft_result"] == "blocked", refused.text
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).merchant == "后来人工修改"
        revisions = db.scalars(select(ExpenseRevision).where(ExpenseRevision.expense_id == expense_id)
            .order_by(ExpenseRevision.revision_number)).all()
        assert [row.change_kind for row in revisions] == ["confirmed", "correction", "correction"]

    page = client.get(f"/web/expenses/{expense_id}/edit?ledger_id={installed.shared_ledger_id}")
    fields = {**_money_fields(page.text, expense_id), "kind": "refund", "original_amount": " 0003.00 ",
        "accounting_date": "2026-09-30", "reason": "原退款原因"}
    action = f"/web/expenses/{expense_id}/offsets"
    first = client.post(action, data=fields, headers=origin)
    repeated = client.post(action, data=fields, headers=origin)
    assert first.status_code == repeated.status_code == 200, (first.text, repeated.text)
    assert first.json() == repeated.json()
    bundle = client.get(f"/api/expenses/{expense_id}/fact-bundle", headers=api_headers).json()
    assert len(bundle["active_offsets"]) == 1
    offset = bundle["active_offsets"][0]
    assert offset["original_amount_minor"] == 300 and bundle["financial_summary"]["lineage_home_net_cents"] == 934
    void_action = f"{action}/{offset['public_id']}/voids"
    page = client.get(f"/web/expenses/{expense_id}/edit?ledger_id={installed.shared_ledger_id}")
    void_fields = {**hidden_post_forms(page.text)[void_action], "void_reason": "原撤销原因"}
    voided = client.post(void_action, data=void_fields, headers=origin)
    repeated = client.post(void_action, data=void_fields, headers=origin)
    assert voided.status_code == repeated.status_code == 200, (voided.text, repeated.text)
    assert voided.json() == repeated.json()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ExpenseOffsetFact).where(ExpenseOffsetFact.expense_id == expense_id)) == 1
        assert db.scalar(select(func.count()).select_from(ExpenseOffsetRevision).where(ExpenseOffsetRevision.expense_id == expense_id)) == 2
        member = db.scalar(select(LedgerMember).where(LedgerMember.account_id == installed.installation_account_id,
            LedgerMember.ledger_id == installed.shared_ledger_id))
        member.role = "viewer"
        db.commit()
    denied = client.post(action, data=fields, headers=origin)
    assert denied.status_code == 403, denied.text
    readonly = client.get(f"/web/expenses/{expense_id}/correct?ledger_id={installed.shared_ledger_id}")
    assert readonly.status_code == 200 and 'data-correction-can-write="false"' in readonly.text
    current = client.get(f"/api/expenses/{expense_id}/fact-bundle", headers=api_headers).json()
    assert current["active_offsets"] == [] and current["financial_summary"]["lineage_home_net_cents"] == 1234
