"""Real-file counterexamples for cleanup whose database commit is rejected."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Expense
from app.services import attachment_cleanup_service, cleanup_service, file_service
from app.services.expense_review_command_service import _commit_confirmation_and_cleanup
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES


@pytest.mark.parametrize("entry", ["after_confirm", "confirmed_retention", "rejected_retention"])
def test_cleanup_commit_failure_preserves_files_without_durable_delete_authority(
    tmp_path, monkeypatch, entry,
):
    upload_dir = tmp_path / "uploads"
    original = upload_dir / "owner" / "2026" / "09" / "original.png"
    thumbnail = original.with_name("thumbnail.png")
    original.parent.mkdir(parents=True)
    original.write_bytes(PNG_BYTES)
    thumbnail.write_bytes(PNG_BYTES)
    settings = SimpleNamespace(upload_dir=upload_dir, delete_image_after_confirm=True,
                               delete_image_after_days=1, delete_rejected_after_days=1)
    monkeypatch.setattr(cleanup_service, "get_settings", lambda: settings)
    monkeypatch.setattr(file_service, "get_settings", lambda: settings)
    monkeypatch.setattr(attachment_cleanup_service, "authorize_currency_metadata_write", lambda _db: None)
    old = now_utc() - timedelta(days=3)
    expense = Expense(id=42, tenant_id="owner", status="rejected" if entry == "rejected_retention" else "confirmed",
                      image_path="uploads/owner/2026/09/original.png", image_deleted_at=None,
                      thumbnail_path="uploads/owner/2026/09/thumbnail.png", thumbnail_deleted_at=None,
                      confirmed_at=old, rejected_at=old, updated_at=old, row_version=7, fact_revision=2)
    fields = ("image_path", "thumbnail_path", "image_deleted_at", "thumbnail_deleted_at",
              "status", "row_version", "fact_revision", "updated_at", "attachment_cleanup_request")
    durable = {field: getattr(expense, field) for field in fields}
    db = Mock(spec=Session)
    db.scalars.return_value = [expense]
    commits = 0

    def commit():
        nonlocal commits
        commits += 1
        # The actual confirmation owner commits the financial fact first.
        if entry == "after_confirm" and commits == 1:
            durable.update({field: getattr(expense, field) for field in fields})
            return
        raise SQLAlchemyError("cleanup commit rejected before durable publication")

    def rollback():
        for field, value in durable.items():
            setattr(expense, field, value)

    db.commit.side_effect = commit
    db.rollback.side_effect = rollback
    with pytest.raises(SQLAlchemyError, match="cleanup commit rejected"):
        if entry == "after_confirm":
            _commit_confirmation_and_cleanup(db, expense)
        elif entry == "confirmed_retention":
            cleanup_service.cleanup_confirmed_images(db, "owner")
        else:
            cleanup_service.cleanup_rejected_images(db, "owner")
    db.rollback()

    assert commits == (2 if entry == "after_confirm" else 1)
    assert durable["image_deleted_at"] is None and durable["thumbnail_deleted_at"] is None
    assert expense.row_version == 7 and expense.fact_revision == 2
    assert {"original_present": original.is_file(), "thumbnail_present": thumbnail.is_file()} == {
        "original_present": True, "thumbnail_present": True,
    }, "A rejected cleanup commit must not leave live references whose bytes were already removed"
