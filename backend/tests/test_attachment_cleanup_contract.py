"""Pure boundary and metadata checks; importing models does not open a database."""

import importlib.util
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import JSONB

from app.attachment_cleanup_contract import ATTACHMENT_CLEANUP_REQUEST_CHECK_SQL, CleanupFile, CleanupRequest
from app.models import Expense

_REQUEST_ID = "424cd9c9-2c4a-4000-8d84-a6470e80b34d"
_NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _request(**changes):
    return {"request_id": _REQUEST_ID, "reason": "after_confirm", "requested_at": _NOW,
            "image": {"reference": "owner/old.jpg"}, **changes}


def test_request_normalizes_utc_and_is_closed_frozen_evidence():
    request = CleanupRequest.model_validate(_request(requested_at=_NOW.astimezone(timezone(timedelta(hours=8)))))
    assert request.request_id == UUID(_REQUEST_ID)
    assert request.requested_at.tzinfo is UTC
    assert request.model_dump(mode="json") == {
        "request_id": _REQUEST_ID, "reason": "after_confirm", "requested_at": "2026-09-20T00:00:00Z",
        "image": {"reference": "owner/old.jpg", "outcome": "pending", "completed_at": None, "error_code": None},
        "thumbnail": None,
    }
    with pytest.raises(ValidationError, match="frozen"):
        request.reason = "confirmed_retention"
    with pytest.raises(ValidationError, match="frozen"):
        request.image.reference = "owner/new.jpg"


@pytest.mark.parametrize("changes", [
    {"request_id": None}, {"request_id": "not-a-uuid"}, {"reason": "delete_all"}, {"task": "delete"},
    {"requested_at": None}, {"requested_at": _NOW.replace(tzinfo=None)}, {"requested_at": 123},
    {"requested_at": "123"}, {"image": None}, {"image": {"reference": ""}},
    {"image": {"reference": "x" * 501}}, {"image": {"reference": 1}},
    {"image": {"reference": "owner/old.jpg", "outcome": "done"}},
    {"image": {"reference": "owner/old.jpg", "extra": "authority"}},
    {"image": {"reference": "owner/old.jpg", "completed_at": _NOW}},
    {"image": {"reference": "owner/old.jpg", "error_code": "raw error text"}},
    {"image": {"reference": "owner/old.jpg", "outcome": "deleted"}},
    {"image": {"reference": "owner/old.jpg", "outcome": "cancelled"}},
    {"image": {"reference": "owner/old.jpg", "outcome": "deleted", "completed_at": _NOW,
               "error_code": "unlink_failed"}},
])
def test_invalid_request_cannot_be_assigned(changes):
    with pytest.raises(ValidationError):
        Expense(attachment_cleanup_request=_request(**changes))


def test_each_file_can_record_a_separate_result_without_mutating_frozen_input():
    image = CleanupFile(reference="owner/old.jpg", error_code="unlink_failed")
    request = CleanupRequest.model_validate(_request(
        image=image, thumbnail={"reference": "owner/old.thumb", "outcome": "deleted", "completed_at": _NOW},
    ))
    expense = Expense(attachment_cleanup_request=request)
    assert expense.attachment_cleanup_request["image"]["error_code"] == "unlink_failed"
    assert expense.attachment_cleanup_request["thumbnail"]["completed_at"] == "2026-09-20T00:00:00Z"
    assert image.outcome == "pending"
    cancelled = CleanupFile(reference="owner/old.jpg", outcome="cancelled", completed_at=_NOW)
    assert cancelled.completed_at == _NOW
    invalid_copy = request.model_copy(update={"image": image.model_copy(update={"outcome": "deleted"})})
    with pytest.raises(ValidationError):
        expense.attachment_cleanup_request = invalid_copy
    expense.attachment_cleanup_request = None
    assert expense.attachment_cleanup_request is None


def test_schema_expansion_keeps_unknown_history_null_and_frozen_migration_aligned():
    for name in ("attachment_cleanup_request", "image_replenished_at"):
        column = Expense.__table__.c[name]
        assert column.nullable and column.default is None and column.server_default is None
    assert isinstance(Expense.__table__.c.attachment_cleanup_request.type, JSONB)
    assert Expense.__table__.c.attachment_cleanup_request.type.none_as_null
    timestamp = Expense.__table__.c.image_replenished_at.type
    assert isinstance(timestamp, DateTime) and timestamp.timezone
    check = next(item for item in Expense.__table__.constraints
                 if isinstance(item, CheckConstraint) and item.name == "ck_expenses_attachment_cleanup_request")
    assert str(check.sqltext) == ATTACHMENT_CLEANUP_REQUEST_CHECK_SQL
    path = Path(__file__).parents[1] / "migrations/versions/20260920_0002_attachment_cleanup_evidence.py"
    spec = importlib.util.spec_from_file_location("attachment_cleanup_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20260920_0002" and migration.down_revision == "20260920_0001"
    assert str(check.sqltext) == migration._CHECK_SQL
