"""Health observes the linked bytes without rewriting the bill or its history."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import AppError
from app.services import file_service

ORIGINAL = b"the admitted original"


@pytest.fixture
def original_health_case(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    source = uploads / "owner" / "receipt.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(ORIGINAL)
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=uploads))
    expense = SimpleNamespace(id=7, public_id="bill-seven", row_version=4, tenant_id="owner",
        image_path="uploads/owner/receipt.png", image_hash=hashlib.sha256(ORIGINAL).hexdigest(),
        image_deleted_at=None, thumbnail_path="uploads/owner/receipt.thumb.webp",
        thumbnail_deleted_at=None, fact_revision=3, amount_minor=1234)
    return expense, source


def _inspect(monkeypatch, expense):
    from app.services import original_health_service

    db = Mock()
    lookup = Mock(return_value=expense)
    monkeypatch.setattr(original_health_service, "get_expense", lookup)
    before = vars(expense).copy()
    result = original_health_service.inspect_expense_original(db, expense_id=7, tenant_id="owner")
    lookup.assert_called_once_with(db, 7, "owner")
    assert vars(expense) == before
    assert db.mock_calls == []
    assert result.expense_id == 7
    assert result.public_id == "bill-seven"
    assert result.row_version == 4
    assert result.checked_at.tzinfo is not None
    assert "uploads/" not in result.model_dump_json()
    return result


def test_health_identifies_actual_bytes_without_financial_or_digest_writes(original_health_case, monkeypatch):
    expense, _ = original_health_case
    result = _inspect(monkeypatch, expense)
    assert result.state == "verified"
    assert result.expected_sha256 == result.observed_sha256 == expense.image_hash
    assert result.size_bytes == len(ORIGINAL)
    assert result.media_type == "image/png"


@pytest.mark.parametrize("recorded", [None, "", "old-hash", "g" * 64])
def test_legacy_health_exposes_review_digest_but_does_not_adopt_it(original_health_case, monkeypatch, recorded):
    expense, _ = original_health_case
    expense.image_hash = recorded
    result = _inspect(monkeypatch, expense)
    assert result.state == "unverified"
    assert result.expected_sha256 is None
    assert result.observed_sha256 == hashlib.sha256(ORIGINAL).hexdigest()


def test_health_cannot_infer_original_from_cached_thumbnail(original_health_case, monkeypatch):
    expense, source = original_health_case
    source.with_name("receipt.thumb.webp").write_bytes(b"usable derivative")
    source.unlink()
    result = _inspect(monkeypatch, expense)
    assert result.state == "missing"
    assert result.observed_sha256 is None


def test_changed_original_is_corrupt_even_when_path_is_present(original_health_case, monkeypatch):
    expense, source = original_health_case
    source.write_bytes(b"another picture")
    result = _inspect(monkeypatch, expense)
    assert result.state == "corrupt"
    assert result.expected_sha256 == expense.image_hash
    assert result.observed_sha256 is None


def test_completed_cleanup_marker_is_distinct_from_missing_file(original_health_case, monkeypatch):
    expense, source = original_health_case
    expense.image_deleted_at = datetime(2026, 9, 20, tzinfo=UTC)
    source.unlink()
    assert _inspect(monkeypatch, expense).state == "cleaned"


def test_manual_bill_with_no_original_is_valid(original_health_case, monkeypatch):
    expense, _ = original_health_case
    expense.image_path = expense.image_hash = None
    assert _inspect(monkeypatch, expense).state == "none"


def test_hash_without_reference_does_not_claim_manual_bill_has_no_original(original_health_case, monkeypatch):
    expense, _ = original_health_case
    expense.image_path = None
    assert _inspect(monkeypatch, expense).state == "missing"


def test_transient_read_failure_is_not_reported_as_lost_original(original_health_case, monkeypatch):
    from app.services import original_health_service

    expense, _ = original_health_case
    monkeypatch.setattr(original_health_service, "read_original_snapshot",
        Mock(side_effect=AppError("image_read_failed", status_code=503)))
    assert _inspect(monkeypatch, expense).state == "unreadable"


def test_unknown_failure_does_not_turn_into_plausible_health(original_health_case, monkeypatch):
    from app.services import original_health_service

    expense, _ = original_health_case
    monkeypatch.setattr(original_health_service, "read_original_snapshot",
        Mock(side_effect=AppError("permission_denied", status_code=403)))
    with pytest.raises(AppError) as rejected:
        _inspect(monkeypatch, expense)
    assert rejected.value.error == "permission_denied"


def test_out_of_scope_bill_fails_before_file_inspection(monkeypatch):
    from app.services import original_health_service

    monkeypatch.setattr(original_health_service, "get_expense",
        Mock(side_effect=AppError("expense_not_found", status_code=404)))
    read = Mock()
    monkeypatch.setattr(original_health_service, "read_original_snapshot", read)
    with pytest.raises(AppError):
        original_health_service.inspect_expense_original(Mock(), expense_id=7, tenant_id="other")
    read.assert_not_called()


@pytest.mark.parametrize("authorized", [True, False])
def test_health_http_entry_requires_account_authority(original_health_case, monkeypatch, authorized):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.auth import get_current_app_context
    from app.database import get_db
    from app.errors import add_exception_handlers
    from app.routes import expense_originals
    from app.services import original_health_service

    expense, _ = original_health_case
    lookup = Mock(return_value=expense)
    monkeypatch.setattr(original_health_service, "get_expense", lookup)
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(expense_originals.router)
    app.dependency_overrides[get_db] = lambda: Mock()

    def authentication():
        if not authorized:
            raise AppError("invalid_token", status_code=401)
        return SimpleNamespace(tenant_id="owner")

    app.dependency_overrides[get_current_app_context] = authentication
    with TestClient(app) as client:
        response = client.get("/api/expenses/7/original")
    assert response.status_code == (200 if authorized else 401)
    if authorized:
        assert response.json()["state"] == "verified"
    else:
        lookup.assert_not_called()
