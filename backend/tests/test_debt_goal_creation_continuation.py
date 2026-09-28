"""A debt-plan task must keep its original identity when creation is retried."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Debt, DebtGoalLink, Goal, Repayment
from tests.debt_repayment_goal_helpers import _create_external_debt, _repay_debt


def test_original_debt_goal_retry_does_not_create_another_plan_after_real_repayment(client, identity):
    debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    key = str(uuid4())
    headers = {**identity.app_headers, "Idempotency-Key": key}
    body = {"name": "还清原欠款", "goal_type": "debt_repayment", "debt_public_ids": [debt["public_id"]]}
    accepted = client.post("/api/goals", headers=headers, json=body)
    assert accepted.status_code == 201, accepted.text
    original = accepted.json()
    payment = _repay_debt(client, identity.app_headers, debt, amount_cents=2000)
    replay = client.post("/api/goals", headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["public_id"] == original["public_id"]
    assert replay.json()["target_amount_cents"] is None
    assert replay.json()["home_currency_code"] is None
    remaining = client.get(f"/api/debts/{debt['public_id']}", headers=identity.app_headers)
    assert remaining.status_code == 200, remaining.text
    assert remaining.json()["remaining_amount_cents"] == payment["remaining_amount_cents"] == 8000
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Goal)) == 1
        goal = db.scalar(select(Goal).where(Goal.public_id == original["public_id"]))
        source = db.scalar(select(Debt).where(Debt.public_id == debt["public_id"]))
        links = list(db.scalars(select(DebtGoalLink).where(DebtGoalLink.goal_id == goal.id)))
        assert [(link.debt_id, link.goal_version) for link in links] == [(source.id, 1)]
        assert source.principal_amount_cents == 10000
        assert db.scalar(select(func.count()).select_from(Repayment)) == 1
        assert source.row_version == payment["row_version"]


@pytest.mark.parametrize("changed_field", ["name", "selection"])
def test_original_debt_goal_key_cannot_replace_its_name_or_debt_selection(client, identity, changed_field):
    first_debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=10000)
    other_debt = _create_external_debt(client, identity.app_headers, principal_amount_cents=20000)
    headers = {**identity.app_headers, "Idempotency-Key": str(uuid4())}
    body = {"name": "原清偿任务", "goal_type": "debt_repayment", "debt_public_ids": [first_debt["public_id"]]}
    accepted = client.post("/api/goals", headers=headers, json=body)
    assert accepted.status_code == 201, accepted.text
    changed = {**body, **({"name": "另一个任务"} if changed_field == "name" else {
        "debt_public_ids": [other_debt["public_id"]],
    })}
    refused = client.post("/api/goals", headers=headers, json=changed)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"] == "idempotency_key_reused"
    replay = client.post("/api/goals", headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["public_id"] == accepted.json()["public_id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Goal)) == 1
        links = list(db.scalars(select(DebtGoalLink)))
        original_debt = db.scalar(select(Debt).where(Debt.public_id == first_debt["public_id"]))
        assert [(link.debt_id, link.goal_version) for link in links] == [(original_debt.id, 1)]
