"""Real command/query consumers retain the original day through replay and calendar changes."""

from uuid import uuid4

from tests._runtime_protocol import negotiated_headers
from tests.debt_proposal_helpers import _create_member_debt, _member_headers
from tests.test_debt_repayment import _create_debt
from tests.test_member_repayment_proposal_cross_ledger import _mint_app_token, _seed_personal_ledger


def _detail(client, headers, public_id):
    response = client.get(f"/api/debts/{public_id}", headers=headers)
    assert response.status_code == 200, response.json()
    return response.json()


def _date_input(detail):
    rule = detail["repayment_calendar"]
    return {"precision": "date_only", "calendar_revision": rule["revision"],
        "user_local_date": "2026-04-30", "accounting_date": "2026-05-01"}


def _change_calendar(client, identity, previous_revision):
    response = client.post("/api/ledgers/owner/calendar",
        headers=negotiated_headers(client, {**identity.app_headers, "Idempotency-Key": str(uuid4())}),
        json={"timezone_name": "Pacific/Honolulu", "expected_revision": previous_revision})
    assert response.status_code == 200, response.json()


def test_date_only_repayment_replays_original_fact_after_calendar_change(client, identity):
    debt = _create_debt(client, identity)
    original_time = _date_input(_detail(client, identity.app_headers, debt["public_id"]))
    body = {"amount_cents": 3000, "expected_row_version": debt["row_version"], "time_input": original_time}
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    url = f"/api/debts/{debt['public_id']}/repayments"
    old_client = client.post(url, headers={**headers, "Ticketbox-Api-Version": "2026-09-13"}, json=body)
    assert old_client.status_code == 409 and old_client.json()["error"] == "client_upgrade_required"
    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 201, first.json()
    assert first.json()["remaining_amount_cents"] == 47000
    _change_calendar(client, identity, original_time["calendar_revision"])
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 201, replay.json()
    assert replay.json()["repayment_public_id"] == first.json()["repayment_public_id"]
    assert replay.json()["row_version"] == first.json()["row_version"]
    facts = client.get(url, headers=identity.app_headers)
    assert facts.status_code == 200 and facts.json()["total"] == 1
    fact = facts.json()["items"][0]
    assert fact["paid_at"] is None and fact["amount_cents"] == 3000
    assert fact["accounting_time"]["user_local_date"] == "2026-04-30"
    assert fact["accounting_time"]["accounting_date"] == "2026-05-01"
    assert fact["accounting_time"]["calendar_revision"] == original_time["calendar_revision"]
    for resource in ("activity", "repayments", "repayment-proposals"):
        for legacy_headers in (identity.auth_headers, {**identity.auth_headers, "Ticketbox-Api-Version": "2026-09-13"}):
            refused = client.get(f"/api/debts/{debt['public_id']}/{resource}", headers=legacy_headers)
            assert refused.status_code == 409 and refused.json()["error"] == "client_upgrade_required"
    changed = client.post(url, headers=headers,
        json={**body, "time_input": {**original_time, "user_local_date": "2026-05-02"}})
    assert changed.status_code == 422 and changed.json()["error"] == "idempotency_key_reused"


def test_member_confirmation_keeps_original_date_after_the_ledger_rule_changes(client, identity):
    personal_ledger = f"repayment-time-{uuid4().hex}"
    member = _seed_personal_ledger(name="跨账本还款人", ledger_id=personal_ledger)
    token = _mint_app_token(account_id=member, ledger_id=personal_ledger)
    member_headers = _member_headers(token)
    debt = _create_member_debt(client, identity.app_headers, direction="owed_to_me", member_account_id=member)
    member_detail = _detail(client, member_headers, debt["public_id"])
    assert member_detail["ledger_id"] is None
    original_time = _date_input(member_detail)
    personal_calendar = client.get(f"/api/ledgers/{personal_ledger}/calendar", headers=member_headers)
    assert personal_calendar.status_code == 200, personal_calendar.json()
    other_zone = "Pacific/Honolulu" if member_detail["repayment_calendar"]["timezone_name"] != "Pacific/Honolulu" else "UTC"
    changed_personal = client.post(f"/api/ledgers/{personal_ledger}/calendar",
        headers=negotiated_headers(client, {**member_headers, "Idempotency-Key": str(uuid4())}),
        json={"timezone_name": other_zone, "expected_revision": personal_calendar.json()["revision"]})
    assert changed_personal.status_code == 200, changed_personal.json()
    assert _detail(client, member_headers, debt["public_id"])["repayment_calendar"] == member_detail["repayment_calendar"]
    url = f"/api/debts/{debt['public_id']}/repayment-proposals"
    submitted = client.post(url, headers={**member_headers, "Idempotency-Key": str(uuid4())},
        json={"proposed_amount_cents": 3000, "time_input": original_time})
    assert submitted.status_code == 201, submitted.json()
    proposal = submitted.json()
    assert proposal["paid_at"] is None
    _change_calendar(client, identity, original_time["calendar_revision"])
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    confirm_url = f"{url}/{proposal['public_id']}/confirm"
    body = {"expected_row_version": debt["row_version"], "confirmed_amount_cents": 2000}
    confirmed = client.post(confirm_url, headers=headers, json=body)
    assert confirmed.status_code == 201, confirmed.json()
    assert confirmed.json()["remaining_amount_cents"] == 48000
    replay = client.post(confirm_url, headers=headers, json=body)
    assert replay.status_code == 201 and replay.json()["row_version"] == confirmed.json()["row_version"]
    history = client.get(f"/api/debts/{debt['public_id']}/repayments", headers=identity.app_headers)
    assert history.status_code == 200 and history.json()["total"] == 1
    fact = history.json()["items"][0]
    assert fact["paid_at"] is None and fact["accounting_time"] == proposal["accounting_time"]
