"""Real PostgreSQL: accepted intent survives concurrency, ACK loss and failure."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ApiIdempotencyKey, Budget, LedgerMember, MonthlyArrangementRevision

_PATH = "/api/budget/arrangements/2026-09"


def _body(**changes):
    return {"home_currency_code": "JPY", "savings_target_cents": 0,
        "reserved_buffer_cents": 100, "expected_row_version": None, **changes}


def _put(client, identity, body=None, key=None, headers=None):
    return client.put(_PATH, json=_body() if body is None else body,
        headers={**(identity.app_headers if headers is None else headers), "Idempotency-Key": key or str(uuid4())})


def _read(client, identity):
    response = client.get(_PATH, headers=identity.app_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_absence_explicit_zero_and_independence_from_budget(client, identity):
    assert _read(client, identity)["arrangement"] is None
    saved = _put(client, identity, _body(reserved_buffer_cents=0))
    assert saved.status_code == 200, saved.text
    assert (saved.json()["savings_target_cents"], saved.json()["reserved_buffer_cents"], saved.json()["row_version"]) == (0, 0, 1)
    assert _read(client, identity)["arrangement"] == saved.json()
    with SessionLocal() as db:
        assert db.scalar(select(Budget).where(Budget.tenant_id == "owner", Budget.month == "2026-09")) is None


def test_ack_replay_keeps_accepted_receipt_after_replacement_and_history_pages(client, identity):
    key = str(uuid4())
    first = _put(client, identity, key=key)
    assert first.status_code == 200, first.text
    second = _put(client, identity, _body(expected_row_version=1, savings_target_cents=300))
    assert second.status_code == 200 and second.json()["row_version"] == 2
    replay = _put(client, identity, key=key)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert _read(client, identity)["arrangement"] == second.json()
    page = client.get("/api/budget/arrangements/2026-09/history", params={"limit": 1}, headers=identity.app_headers).json()
    assert page["items"][0]["row_version"] == 2 and page["items"][0]["savings_target_cents"] == 300
    earlier = client.get("/api/budget/arrangements/2026-09/history", params={"before_version": page["next_before_version"]}, headers=identity.app_headers).json()
    assert len(earlier["items"]) == 1 and earlier["items"][0]["savings_target_cents"] == 0
    assert earlier["items"][0]["home_currency_code"] == "JPY"


@pytest.mark.parametrize("change", [{"expected_row_version": None}, {"expected_row_version": 2},
    {"expected_row_version": 1, "home_currency_code": "CNY"}])
def test_conflict_preserves_fact_history_and_rejected_claim_can_retry(client, identity, change):
    first = _put(client, identity)
    assert first.status_code == 200
    key = str(uuid4())
    refused = _put(client, identity, _body(savings_target_cents=999, **change), key=key)
    assert refused.status_code == 409, refused.text
    assert _read(client, identity)["arrangement"] == first.json()
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
        assert len(db.scalars(select(MonthlyArrangementRevision).where(MonthlyArrangementRevision.tenant_id == "owner")).all()) == 1
    retry = _put(client, identity, _body(expected_row_version=1, savings_target_cents=999), key=key)
    assert retry.status_code == 200 and retry.json()["row_version"] == 2


def test_key_binds_actor_and_intent_and_missing_key_is_refused(client, identity):
    key = str(uuid4())
    assert _put(client, identity, key=key).status_code == 200
    assert _put(client, identity, _body(savings_target_cents=100), key=key).status_code == 422
    assert client.put(_PATH, json=_body(), headers=identity.app_headers).status_code == 422
    legacy = client.put(_PATH, json=_body(), headers=identity.auth_headers)
    assert legacy.status_code == 409 and legacy.json()["error"] == "client_upgrade_required"


def test_readers_and_other_ledgers_cannot_change_or_see_selected_fact(client, identity):
    assert _put(client, identity).status_code == 200
    other = client.get(_PATH, headers=identity.gray_app_headers)
    assert other.status_code == 200 and other.json()["arrangement"] is None
    assert client.get("/api/budget/arrangements/2026-09/history", headers=identity.gray_app_headers).json()["items"] == []
    with SessionLocal.begin() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == "owner"))
        member.role = "viewer"
    assert _read(client, identity)["arrangement"]["row_version"] == 1
    assert _put(client, identity, _body(expected_row_version=1)).status_code == 403


def test_history_failure_rolls_back_projection_history_and_command_receipt(client, identity, monkeypatch):
    from app.errors import AppError
    from app.services import monthly_arrangement_service as command

    first = _put(client, identity)
    key = str(uuid4())

    def fail(*args, **kwargs):
        raise AppError("state_conflict", status_code=409)

    monkeypatch.setattr(command, "record_monthly_arrangement_revision", fail)
    failed = _put(client, identity, _body(expected_row_version=1, savings_target_cents=999), key=key)
    assert failed.status_code == 409
    assert _read(client, identity)["arrangement"] == first.json()
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
        assert len(db.scalars(select(MonthlyArrangementRevision).where(MonthlyArrangementRevision.tenant_id == "owner")).all()) == 1


def test_invalid_month_money_and_history_cursor_do_not_create_facts(client, identity):
    assert client.put("/api/budget/arrangements/2026-13", json=_body(),
        headers={**identity.app_headers, "Idempotency-Key": str(uuid4())}).status_code == 422
    assert _put(client, identity, _body(savings_target_cents=-1)).status_code == 422
    assert client.get("/api/budget/arrangements/2026-09/history", params={"before_version": 0}, headers=identity.app_headers).status_code == 422
    assert _read(client, identity)["arrangement"] is None


def test_unauthenticated_save_is_rejected_before_claiming_or_changing_facts(client, identity):
    first = _put(client, identity)
    assert first.status_code == 200, first.text
    history = client.get("/api/budget/arrangements/2026-09/history", headers=identity.app_headers).json()
    key = str(uuid4())
    refused = client.put("/api/budget/arrangements/2026-09", json=_body(expected_row_version=1, savings_target_cents=999),
        headers={"Idempotency-Key": key})
    assert refused.status_code == 401, refused.text
    assert _read(client, identity)["arrangement"] == first.json()
    assert client.get("/api/budget/arrangements/2026-09/history", headers=identity.app_headers).json() == history
    with SessionLocal() as db:
        assert db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == key)) is None
