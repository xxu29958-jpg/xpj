"""Real command/HTTP journeys; use the existing PostgreSQL test runtime."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Debt, MemberRepaymentProposal, Repayment
from tests._runtime_protocol import current_protocol_headers
from tests.debt_proposal_helpers import (
    _create_member_debt,
    _idem,
    _member_headers,
    _mint_member_actor,
    _propose,
)
from tests.test_debt_repayment_activity import (
    _create_external_debt,
    _record_repayment,
    _seed_cross_ledger_member_debt,
    _set_owner_role,
    _void_repayment,
)


def _activity(client, headers, public_id, **params):
    response = client.get(f"/api/debts/{public_id}/activity", headers=headers, params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def _write(client, headers, public_id, action, body):
    response = client.post(f"/api/debts/{public_id}/{action}", headers=_idem(headers), json=body)
    assert response.status_code == 201, response.json()
    return response.json()


def test_real_commands_survive_in_activity_after_single_and_whole_debt_void(client: TestClient, identity):
    debt = _create_external_debt(client, identity.app_headers)
    repaid = _record_repayment(client, identity.app_headers, debt, amount_cents=3_000)
    adjusted = _write(client, identity.app_headers, debt["public_id"], "adjustments", {
        "amount_cents": -500, "reason": "Correct original balance", "expected_row_version": repaid["row_version"]})
    restored = _void_repayment(client, identity.app_headers, adjusted,
        repayment_public_id=repaid["repayment_public_id"], reason="Duplicate transfer")
    voided = _write(client, identity.app_headers, debt["public_id"], "void", {
        "reason": "Duplicate obligation", "expected_row_version": restored["row_version"]})

    body = _activity(client, identity.app_headers, debt["public_id"])
    assert body["total"] == 5
    assert body["debt_public_id"] == debt["public_id"] and body["home_currency_code"] == "CNY"
    by_kind = {item["kind"]: item for item in body["items"]}
    assert set(by_kind) == {"created", "adjustment", "repayment", "repayment_void", "debt_void"}
    assert by_kind["created"]["amount_cents"] == 10_000
    assert by_kind["adjustment"]["amount_cents"] == -500
    assert by_kind["adjustment"]["reason"] == "Correct original balance"
    payment = by_kind["repayment"]["repayment"]
    assert payment["public_id"] == repaid["repayment_public_id"] and payment["amount_cents"] == 3_000
    assert payment["status"] == "voided" and payment["void_fact"]["reason"] == "Duplicate transfer"
    assert by_kind["repayment_void"]["repayment"] == payment
    assert by_kind["debt_void"]["amount_cents"] is None
    assert by_kind["debt_void"]["reason"] == "Duplicate obligation"
    assert all(item["recorded_at"].endswith("Z") and item["actor_is_you"] for item in body["items"])
    # The old compatible repayment reader remains available to its existing consumers.
    old = client.get(f"/api/debts/{debt['public_id']}/repayments", headers=identity.app_headers)
    assert old.status_code == 200 and old.json()["items"] == [payment]
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["status"] == "voided" and detail["row_version"] == voided["row_version"]
    assert detail["paid_amount_cents"] == 0


def test_partial_confirmation_and_forgiveness_preserve_one_payment_and_both_proposal_events(
    client: TestClient, identity,
):
    member_id, member_token = _mint_member_actor()
    debt = _create_member_debt(client, identity.app_headers, direction="owed_to_me", member_account_id=member_id)
    proposal_response = _propose(client, _member_headers(member_token), debt["public_id"], proposed_amount_cents=10_000)
    assert proposal_response.status_code == 201, proposal_response.json()
    proposal = proposal_response.json()
    before = _activity(client, identity.app_headers, debt["public_id"])
    assert {item["kind"] for item in before["items"]} == {"created", "proposal_created"}
    detail = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers).json()
    assert detail["paid_amount_cents"] == 0
    assert detail["row_version"] == debt["row_version"]

    confirmation_headers = _idem(identity.app_headers)
    confirmation_body = {"confirmed_amount_cents": 4_000, "expected_row_version": debt["row_version"]}
    url = f"/api/debts/{debt['public_id']}/repayment-proposals/{proposal['public_id']}/confirm"
    confirmed = client.post(url, headers=confirmation_headers, json=confirmation_body)
    assert confirmed.status_code == 201, confirmed.json()
    replay = client.post(url, headers=confirmation_headers, json=confirmation_body)
    assert replay.status_code == 201, replay.json()
    assert confirmed.json()["paid_amount_cents"] == 4_000
    assert confirmed.json()["remaining_amount_cents"] == 46_000
    after = _activity(client, identity.app_headers, debt["public_id"])
    assert after["total"] == 4
    proposals = [item for item in after["items"] if item["proposal"] is not None]
    assert {(item["kind"], item["public_id"]) for item in proposals} == {
        ("proposal_created", proposal["public_id"]), ("proposal_resolved", proposal["public_id"])}
    payments = [item for item in after["items"] if item["kind"] == "repayment"]
    assert len(payments) == 1
    assert payments[0]["repayment"]["amount_cents"] == 4_000
    for item in proposals:
        assert item["amount_cents"] is None
        assert item["repayment"] is None
        assert item["proposal"]["proposed_amount_cents"] == 10_000
        assert item["proposal"]["confirmed_amount_cents"] == 4_000
        assert item["proposal"]["status"] == "partially_confirmed"
        assert item["proposal"]["committed_repayment_public_id"] == payments[0]["public_id"]
        assert item["actor_is_you"] == (item["kind"] == "proposal_resolved")
    with SessionLocal() as db:
        stored = db.scalar(select(MemberRepaymentProposal).where(MemberRepaymentProposal.public_id == proposal["public_id"]))
        facts = list(db.scalars(select(Repayment).where(Repayment.proposal_id == stored.id)))
        assert len(facts) == 1 and facts[0].id == stored.committed_repayment_id
        assert facts[0].amount_cents == 4_000

    forgiven = _write(client, identity.app_headers, debt["public_id"], "forgive", {
        "expected_row_version": confirmed.json()["row_version"]})
    final = _activity(client, identity.app_headers, debt["public_id"])
    assert final["total"] == 5
    forgiveness = next(item for item in final["items"] if item["kind"] == "forgiveness")
    assert forgiveness["amount_cents"] == 46_000 and forgiveness["repayment"] is None
    assert forgiven["is_forgiven"] and forgiven["paid_amount_cents"] == 4_000
    assert forgiven["remaining_amount_cents"] == 0


def test_activity_viewer_read_auth_bounds_and_stranger_existence_hiding(client: TestClient, identity):
    debt = _create_external_debt(client, identity.app_headers)
    _set_owner_role("viewer")
    body = _activity(client, identity.app_headers, debt["public_id"])
    assert body["total"] == 1 and body["items"][0]["kind"] == "created"
    unauthenticated = client.get(f"/api/debts/{debt['public_id']}/activity")
    assert unauthenticated.status_code == 401 and unauthenticated.json()["error"] == "invalid_token"
    for params in ({"page_size": 101}, {"page_size": 0}, {"page": 0}):
        response = client.get(f"/api/debts/{debt['public_id']}/activity", headers=identity.app_headers, params=params)
        assert response.status_code == 422 and response.json()["error"] == "invalid_request"
    for public_id in (debt["public_id"], "not-a-debt"):
        response = client.get(f"/api/debts/{public_id}/activity", headers=identity.gray_app_headers)
        assert response.status_code == 404 and response.json()["error"] == "debt_not_found"


def test_real_cross_ledger_participant_reads_shared_history_without_private_ledger(client: TestClient, identity):
    public_id, debtor_token = _seed_cross_ledger_member_debt()
    debtor_headers = current_protocol_headers({"Authorization": f"Bearer {debtor_token}"})
    proposed = _propose(client, debtor_headers, public_id, proposed_amount_cents=1_000)
    assert proposed.status_code == 201, proposed.json()
    confirmed = _write(client, identity.app_headers, public_id,
        f"repayment-proposals/{proposed.json()['public_id']}/confirm", {"expected_row_version": 1})
    assert confirmed["ledger_id"] is None and confirmed["paid_amount_cents"] == 1_000
    body = _activity(client, identity.app_headers, public_id)
    assert body["total"] == 4
    assert {item["kind"] for item in body["items"]} == {"created", "proposal_created", "proposal_resolved", "repayment"}
    response_text = str(body)
    for private in ("ledger_id", "tenant_id", "actor_account_id", "debtor_account_id", "creditor_account_id",
                    "idempotency_key", "image_path", "debtor-"):
        assert private not in response_text
    # The gray device belongs to the same creditor Account, so its other
    # ledger context must preserve the authorized counterparty history.
    assert _activity(client, identity.gray_app_headers, public_id) == body
    _, stranger_token = _mint_member_actor()
    denied = client.get(f"/api/debts/{public_id}/activity", headers=_member_headers(stranger_token))
    assert denied.status_code == 404 and denied.json()["error"] == "debt_not_found"


def test_http_focus_uses_the_actual_repayment_page_and_rejects_foreign_fact(client: TestClient, identity):
    debt = _create_external_debt(client, identity.app_headers)
    current = debt
    payments = []
    for _ in range(4):
        current = _record_repayment(client, identity.app_headers, current, amount_cents=100)
        payments.append(current["repayment_public_id"])
    focused = _activity(client, identity.app_headers, debt["public_id"], page_size=2, focus_repayment=payments[0])
    assert focused["page"] == 2 and focused["total"] == 5
    assert payments[0] in [item["public_id"] for item in focused["items"]]
    oldest = _activity(client, identity.app_headers, debt["public_id"], page=3, page_size=2)
    assert oldest["total"] == 5 and [item["kind"] for item in oldest["items"]] == ["created"]
    other = _create_external_debt(client, identity.app_headers)
    for focus in (payments[0], "missing-repayment"):
        response = client.get(f"/api/debts/{other['public_id']}/activity", headers=identity.app_headers,
            params={"focus_repayment": focus})
        assert response.status_code == 404 and response.json()["error"] == "repayment_not_found"
    with SessionLocal() as db:
        original = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        assert original.row_version == current["row_version"]
