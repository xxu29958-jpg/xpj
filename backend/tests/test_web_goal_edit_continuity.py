"""A real Web goal form must share the API command and preserve refused input."""

from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms
from tests.spending_goal_test_support import _editor, _goal


def test_real_editor_replays_original_key_without_a_second_goal_revision(web_client, identity):
    goal = _goal(web_client, identity)
    action, fields = _editor(web_client, goal["public_id"], include_archived=True)
    assert fields["return_month"] == "2026-05" and fields["return_include_archived"] == "true"
    fields.update(name="调整后的目标", month="2026-06", target_amount_yuan="350.25", category="")
    first = web_client.post(action, data=fields, follow_redirects=False)
    assert first.status_code == 303, first.text
    assert "month=2026-06" in first.headers["location"]
    assert "include_archived=true" in first.headers["location"]
    assert first.headers["location"].endswith(f'#goal-{goal["public_id"]}')
    replay = web_client.post(action, data=fields, follow_redirects=False)
    assert replay.status_code == 303, replay.text
    canonical = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert canonical["name"] == "调整后的目标"
    assert canonical["month"] == "2026-06"
    assert canonical["category"] is None
    assert canonical["target_amount_cents"] == 35025
    assert canonical["row_version"] == goal["row_version"] + 1
    fields.update(name="第二次修改", target_amount_yuan="400.00")
    reused = web_client.post(action, data=fields)
    assert reused.status_code == 422, reused.text
    assert 'value="第二次修改"' in reused.text and 'name="review_latest"' in reused.text
    retained = hidden_post_forms(reused.text)[action]
    assert retained["idempotency_key"] == fields["idempotency_key"]
    review = web_client.post(action, data={**fields, "review_latest": "true"})
    assert review.status_code == 200
    proposal = hidden_post_forms(review.text)[action]
    assert proposal["idempotency_key"] != fields["idempotency_key"]
    assert int(proposal["expected_row_version"]) == canonical["row_version"]
    proposal.update(name="第二次修改", month="2026-06", target_amount_yuan="400.00", category="")
    assert web_client.post(action, data=proposal, follow_redirects=False).status_code == 303
    final = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert final["target_amount_cents"] == 40000 and final["row_version"] == canonical["row_version"] + 1


def test_validation_and_occ_refusals_keep_input_original_key_and_original_version(web_client, identity):
    goal = _goal(web_client, identity)
    action, fields = _editor(web_client, goal["public_id"])
    fields.update(name="尚未保存的修改", month="2026-05", target_amount_yuan="bad-amount", category="交通")
    invalid = web_client.post(action, data=fields)
    assert invalid.status_code == 422
    assert 'value="尚未保存的修改"' in invalid.text and 'value="bad-amount"' in invalid.text
    assert hidden_post_forms(invalid.text)[action]["idempotency_key"] == fields["idempotency_key"]
    updated = web_client.patch(f'/api/goals/{goal["public_id"]}', headers={
        **negotiated_headers(web_client, identity.app_headers), "Idempotency-Key": "parallel-goal-edit",
    }, json={"home_currency_code": "CNY", "name": "另一端已保存", "expected_row_version": goal["row_version"]})
    assert updated.status_code == 200, updated.text
    fields["target_amount_yuan"] = "350.25"
    refused = web_client.post(action, data=fields)
    assert refused.status_code == 409, refused.text
    assert 'value="尚未保存的修改"' in refused.text and 'value="350.25"' in refused.text
    retained = hidden_post_forms(refused.text)[action]
    assert retained["expected_row_version"] == fields["expected_row_version"]
    assert retained["idempotency_key"] == fields["idempotency_key"]
    canonical = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert canonical["name"] == "另一端已保存" and canonical["target_amount_cents"] == 20000
    review = web_client.post(action, data={**fields, "review_latest": "true"})
    assert review.status_code == 200, review.text
    assert 'value="尚未保存的修改"' in review.text and "另一端已保存" in review.text
    proposal = hidden_post_forms(review.text)[action]
    assert int(proposal["expected_row_version"]) == canonical["row_version"]
    assert proposal["idempotency_key"] != fields["idempotency_key"]
    unchanged = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert unchanged == canonical
    proposal.update(name=fields["name"], month=fields["month"], category=fields["category"], target_amount_yuan="350.25")
    assert web_client.post(action, data=proposal, follow_redirects=False).status_code == 303


def test_viewer_and_other_ledger_cannot_reuse_the_goal_editor(web_client, identity):
    goal = _goal(web_client, identity)
    action, fields = _editor(web_client, goal["public_id"])
    fields.update(name="禁止的修改", month="2026-05", target_amount_yuan="99", category="餐饮")
    foreign = web_client.post(action, data={**fields, "ledger_id": "gray"})
    assert foreign.status_code == 400, foreign.text
    assert foreign.json()["error"] == "invalid_request"
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner").limit(1))
        assert member is not None
        member.role = "viewer"
        db.commit()
    page = web_client.get("/web/goals?ledger_id=owner&month=2026-05")
    assert f'/web/goals/{goal["public_id"]}/edit?' not in page.text
    assert web_client.post(action, data=fields).status_code == 403
    canonical = web_client.get(f'/api/goals/{goal["public_id"]}', headers=identity.app_headers).json()
    assert canonical["target_amount_cents"] == 20000 and canonical["row_version"] == goal["row_version"]
