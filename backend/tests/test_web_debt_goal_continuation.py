"""Real installed browser tasks retain receipts, binding and explicit conflict review."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Debt, Goal, LedgerMember
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms
from tests.debt_repayment_goal_helpers import _create_debt_goal, _create_external_debt, _replace_links, _set_target_date


@pytest.fixture
def installed_debt_browser():
    yield from installed_web_setup()


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
@pytest.mark.parametrize("task", ["create", "links", "target-date"])
def test_bound_debt_goal_task_replays_its_original_receipt_after_later_edit_and_refuses_rebinding(installed_debt_browser, task):
    installed = installed_debt_browser
    _connect_local_session(installed)
    browser = installed.browser
    browser.base_url = browser.base_url.copy_with(scheme="https")
    headers = {"Origin": str(browser.base_url).rstrip("/"), "Accept": "application/json"}
    create_action = "/web/debt-goals/create"
    fields = hidden_post_forms(browser.get("/web/debt-goals/new").text)[create_action]
    scope = json.loads(fields["draft_scope"])
    with SessionLocal() as db:
        debt = Debt(tenant_id=scope["ledgerId"], owner_account_id=installed.installation_account_id,
            created_by_account_id=installed.installation_account_id, direction="i_owe", counterparty_type="external",
            counterparty_label="原欠款", principal_amount_cents=10000, home_currency_code="CNY", status="open", source_type="manual")
        db.add(debt)
        db.commit()
        debt_id = debt.public_id
    fields.update(name="  年底原任务  ", debt_public_ids=[debt_id])
    created = browser.post(create_action, data=fields, headers=headers)
    assert created.status_code == 200, created.text
    public_id = created.json()["receipt"]["public_id"]
    action = create_action
    original = created.json()
    if task != "create":
        action = f"/web/debt-goals/{public_id}/{task}"
        fields = hidden_post_forms(browser.get(action).text)[action]
        fields.update(debt_public_ids=[debt_id], target_date="2030-12-31")
        accepted = browser.post(action, data=fields, headers=headers)
        assert accepted.status_code == 200, accepted.text
        original = accepted.json()
    date_action = f"/web/debt-goals/{public_id}/target-date"
    later = hidden_post_forms(browser.get(date_action).text)[date_action]
    later["target_date"] = "2031-12-31"
    changed = browser.post(date_action, data=later, headers=headers)
    assert changed.status_code == 200, changed.text
    replay = browser.post(action, data=fields, headers=headers)
    assert replay.status_code == 200 and replay.json() == original, replay.text
    assert original["ack"] == {"scope": scope, "clientRef": fields["idempotency_key"]}
    assert changed.json()["receipt"]["row_version"] > original["receipt"]["row_version"]
    changed_scope = {**scope, "deviceId": "replacement-browser"}
    refused = browser.post(action, data={**fields, "draft_scope": json.dumps(changed_scope)}, headers=headers)
    assert refused.status_code == 409 and refused.json()["error"] == "session_binding_changed", refused.text
    with SessionLocal() as db:
        membership = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == scope["ledgerId"],
            LedgerMember.account_id == installed.installation_account_id))
        membership.role = "viewer"
        db.commit()
    denied = browser.post(action, data=fields, headers=headers)
    assert denied.status_code == 403 and denied.json()["draft_result"] == "blocked", denied.text
    with SessionLocal() as db:
        goals = list(db.scalars(select(Goal).where(Goal.tenant_id == scope["ledgerId"])))
        assert len(goals) == 1 and goals[0].target_date.isoformat() == "2031-12-31"
        assert goals[0].row_version == changed.json()["receipt"]["row_version"]
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.tenant_id == scope["ledgerId"],
            ApiIdempotencyKey.idempotency_key == fields["idempotency_key"]))
        assert claim.response_body == original["receipt"]


def test_api_and_web_share_original_debt_link_receipt_and_legacy_receipt_requires_review(web_client, identity):
    first = _create_external_debt(web_client, identity.app_headers)
    other = _create_external_debt(web_client, identity.app_headers)
    goal = _create_debt_goal(web_client, identity.app_headers, name="原目标", debt_public_ids=[first["public_id"]]).json()
    key = str(uuid4())
    original = _replace_links(web_client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"],
        debt_public_ids=[first["public_id"], other["public_id"]], idempotency_key=key)
    assert original.status_code == 200, original.text
    changed = _set_target_date(web_client, identity.app_headers, goal["public_id"],
        expected_row_version=original.json()["row_version"], target_date="2031-12-31")
    assert changed.status_code == 200, changed.text
    replay = _replace_links(web_client, identity.app_headers, goal["public_id"], expected_row_version=goal["row_version"],
        debt_public_ids=[first["public_id"], other["public_id"]], idempotency_key=key)
    assert replay.json() == original.json()
    with SessionLocal() as db:
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key))
        assert claim.response_body == original.json()
        claim.response_body = None
        db.commit()
    form = {"ledger_id": "owner", "idempotency_key": key, "expected_row_version": str(goal["row_version"]),
        "debt_public_ids": [first["public_id"], other["public_id"]]}
    review = web_client.post(f"/web/debt-goals/{goal['public_id']}/links", data=form)
    assert review.status_code == 409 and "缺少原回执" in review.text
    current = web_client.get(f"/api/goals/{goal['public_id']}", headers=identity.app_headers).json()
    assert current["row_version"] == changed.json()["row_version"]
    assert current["debt_repayment"]["target_date"] == "2031-12-31"
