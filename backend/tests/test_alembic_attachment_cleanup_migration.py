"""PostgreSQL proof of the nullable cleanup edge and its direct-SQL backstop."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260920_0001"
_HEAD = "20260920_0002"
_REQUEST = {
    "request_id": "424cd9c9-2c4a-4000-8d84-a6470e80b34d",
    "reason": "after_confirm", "requested_at": "2026-09-20T00:00:00Z",
    "image": {"reference": "owner/old.jpg", "outcome": "pending", "completed_at": None, "error_code": None},
    "thumbnail": None,
}


def _snapshot():
    with engine.connect() as db:
        return dict(db.execute(text("SELECT * FROM expenses")).mappings().one())


@pytest.fixture
def cleanup_edge():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("""
                INSERT INTO expenses (public_id, tenant_id, amount_cents, original_amount_minor,
                    merchant, category, source, duplicate_status, status, image_path, thumbnail_path,
                    created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'owner', 100, 100, 'Original merchant', '其他', 'manual', 'none',
                    'confirmed', 'owner/old.jpg', 'owner/old.thumb', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 1)
            """), {"id": str(uuid4())})
        yield _snapshot()
    finally:
        reset_schema()


def test_cleanup_expansion_preserves_exact_history_and_empty_edge_round_trips(cleanup_edge):
    run_alembic(command.upgrade, _HEAD)
    after = _snapshot()
    assert after.pop("attachment_cleanup_request") is None
    assert after.pop("image_replenished_at") is None
    assert after == cleanup_edge
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
    run_alembic(command.downgrade, _PARENT)
    assert _snapshot() == cleanup_edge
    assert "attachment_cleanup_request" not in {column["name"] for column in inspect(engine).get_columns("expenses")}
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _PARENT


@pytest.mark.parametrize("field", ["attachment_cleanup_request", "image_replenished_at"])
def test_downgrade_cannot_discard_either_kind_of_attachment_evidence(cleanup_edge, field):
    run_alembic(command.upgrade, _HEAD)
    value = json.dumps(_REQUEST) if field == "attachment_cleanup_request" else "2026-09-20T00:00:00Z"
    cast = "jsonb" if field == "attachment_cleanup_request" else "timestamptz"
    with SessionLocal.begin() as db:
        activate_test_currency_authority(db, "CNY")
        db.execute(text(f"UPDATE expenses SET {field} = CAST(:value AS {cast})"), {"value": value})
    before = _snapshot()
    with pytest.raises(RuntimeError, match="cannot discard attachment cleanup or replenishment evidence"):
        run_alembic(command.downgrade, _PARENT)
    assert _snapshot() == before
    with engine.connect() as db:
        assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD


def test_direct_sql_cannot_bypass_closed_cleanup_request_shape(cleanup_edge):
    run_alembic(command.upgrade, _HEAD)
    invalid = [None, [], "arbitrary task", {}, {**_REQUEST, "extra": "authority"},
               {**_REQUEST, "request_id": None}, {**_REQUEST, "request_id": "not-a-uuid"},
               {**_REQUEST, "reason": "delete_all"}, {**_REQUEST, "requested_at": 123},
               {**_REQUEST, "requested_at": "2026-09-20T00:00:00"}, {**_REQUEST, "image": None}]
    for changes in ({"reference": ""}, {"reference": "x" * 501}, {"reference": 1},
                    {"extra": "authority"}, {"outcome": "done"}, {"completed_at": _REQUEST["requested_at"]},
                    {"error_code": "raw secret"}, {"outcome": "deleted"},
                    {"outcome": "cancelled", "completed_at": _REQUEST["requested_at"], "error_code": "unlink_failed"}):
        invalid.append({**_REQUEST, "image": {**_REQUEST["image"], **changes}})
    for value in invalid:
        with pytest.raises(IntegrityError, match="ck_expenses_attachment_cleanup_request"), SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("UPDATE expenses SET attachment_cleanup_request = CAST(:value AS jsonb)"),
                       {"value": json.dumps(value)})
    for outcome in ("pending", "deleted", "cancelled"):
        value = deepcopy(_REQUEST)
        value["image"]["outcome"] = outcome
        if outcome != "pending":
            value["image"]["completed_at"] = value["requested_at"]
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            db.execute(text("UPDATE expenses SET attachment_cleanup_request = CAST(:value AS jsonb)"),
                       {"value": json.dumps(value)})
        assert _snapshot()["attachment_cleanup_request"] == value
