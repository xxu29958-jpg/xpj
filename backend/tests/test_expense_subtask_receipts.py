"""Original subtask receipts cannot lend a peer's OCC token to offline work.

The actual routes, domain writers, CAS, receipt rows and transactions run on
PostgreSQL; authentication is controlled at this command boundary.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.errors import AppError
from app.models import ApiIdempotencyKey
from tests.web_expense_fact_test_support import _facts, _prepare, _submit
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_replay_preserves_first_receipt_and_next_intent_conflicts_with_peer(confirmation_store, kind):
    with confirmation_store() as db:
        original_version = _prepare(db, kind)
        first = _submit(db, kind, original_version, "original-key").model_dump(mode="json")
    with confirmation_store() as db:
        _submit(db, "splits" if kind == "splits" else "items", first["row_version"], "peer-key",
            label="他端后来填写", amount=700)
        peer_facts = _facts(db)
    with confirmation_store() as db:
        replay = _submit(db, kind, original_version, "original-key").model_dump(mode="json")
        # This is the next token actually consumed by Android's outbox cascade.
        with pytest.raises(AppError) as conflict:
            _submit(db, "splits" if kind == "splits" else "items", replay["row_version"], "following-key",
                label="后续离线原稿", amount=900)
        assert conflict.value.error == "state_conflict"
        db.rollback()
        assert replay == first
        assert _facts(db) == peer_facts
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == "original-key")).response_body == first


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_accepted_subtask_without_original_receipt_requires_review(confirmation_store, kind):
    with confirmation_store() as db:
        original_version = _prepare(db, kind)
        _submit(db, kind, original_version, "original-key")
        before = _facts(db)
        claim = db.scalar(select(ApiIdempotencyKey).where(ApiIdempotencyKey.idempotency_key == "original-key"))
        claim.response_body = None
        db.commit()
    with confirmation_store() as db:
        with pytest.raises(AppError) as refusal:
            _submit(db, kind, original_version, "original-key")
        assert refusal.value.error == "expense_subtask_original_requires_review"
        assert _facts(db) == before


@pytest.mark.parametrize("kind", ["items", "splits", "ack"])
def test_subtask_and_first_receipt_roll_back_together(confirmation_store, kind, monkeypatch):
    with confirmation_store() as db:
        original_version = _prepare(db, kind)
        before = _facts(db)
    from app.services import expense_subtask_command_service as owner

    def fail(*args, **kwargs):
        raise SQLAlchemyError("injected receipt failure")

    monkeypatch.setattr(owner, "mark_idempotency_succeeded", fail)
    with confirmation_store() as db, pytest.raises(SQLAlchemyError, match="injected receipt failure"):
        _submit(db, kind, original_version, "original-key")
    with confirmation_store() as db:
        assert _facts(db) == before
        assert db.scalar(select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.idempotency_key == "original-key")) is None
