"""Every transaction identity in a notification batch commits or rolls back together."""
from uuid import uuid4

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Expense, PaymentCapture
from tests.test_notification_time_review import _capture


def _batch(amounts=(1000, 1290, 2933)):
    return {"captures": [{**_capture(), "notification_key": str(uuid4()), "original_amount_minor": amount}
        for amount in amounts]}


def test_batch_requires_auth_before_creating_any_candidate(client):
    body = _batch()
    assert client.post("/api/payment-captures/batch", json=body).status_code == 401
    assert client.post("/api/payment-captures/batch", headers={"Authorization": "Bearer invalid"}, json=body).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentCapture)) == 0
        assert db.scalar(select(func.count()).select_from(Expense)) == 0


def test_batch_preserves_three_independent_candidates_and_replays_after_a_lost_response(client, identity):
    body = _batch()
    response = client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body)
    assert response.status_code == 201, response.text
    captures = response.json()
    assert [item["original_amount_minor"] for item in captures] == [1000, 1290, 2933]
    assert len({item["expense_id"] for item in captures}) == 3
    assert client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body).json() == captures
    for original, result in zip(body["captures"], captures, strict=True):
        assert client.post("/api/payment-captures", headers=identity.app_headers, json=original).json() == result
        assert result["recognition_time"]["candidates"]
        assert client.get(f"/api/expenses/{result['expense_id']}", headers=identity.gray_app_headers).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentCapture)) == 3
        assert db.scalar(select(func.count()).select_from(Expense)) == 3


def test_batch_bad_later_candidate_rolls_back_every_earlier_reservation_and_can_recover(client, identity):
    body = _batch()
    # Semantic source validation happens during staging, after schema acceptance.
    body["captures"][-1]["source"] = "unsupported"
    response = client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(PaymentCapture)) == 0
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
    body["captures"][-1]["source"] = "alipay"
    assert client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body).status_code == 201


def test_same_amount_events_stay_separate_and_duplicate_identity_is_rejected(client, identity):
    body = _batch((1000, 1000))
    response = client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body)
    assert response.status_code == 201 and len({row["expense_id"] for row in response.json()}) == 2
    body["captures"][1]["notification_key"] = body["captures"][0]["notification_key"]
    assert client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body).status_code == 422


def test_more_than_twenty_four_candidates_are_retained(client, identity):
    body = _batch(tuple(range(1000, 1030)))
    body["captures"][0]["candidates"] = [{"kind": "expense", "amount_minor": 1000 + index,
        "field": "text", "evidence": "amount_bound_expense"} for index in range(30)]
    response = client.post("/api/payment-captures/batch", headers=identity.app_headers, json=body)
    assert response.status_code == 201, response.text
    assert len(response.json()) == 30 and len(response.json()[0]["candidates"]) == 30
