"""First attachment uses the real Web command, SQLite receipt and admitted file.

Identity/currency/publication fences are controlled here; real PostgreSQL owns
their qualification. Financial facts, CAS, receipt settlement and bytes are real.
"""
import hashlib
import json
from dataclasses import replace
from datetime import UTC, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.errors import AppError
from app.models import ApiIdempotencyKey, Expense, LedgerAuditLog
from app.routes import web_originals
from app.services import attachment_cleanup_service as cleanup
from app.services import file_service, manual_expense_draft_presenter, original_command_service
from app.services.time_service import now_utc
from app.tenants import AuthContext
from tests import test_expense_confirmation_receipt as receipt_tests
from tests import test_web_expense_confirmation_page as page_tests
from tests.test_original_replenishment_admission import _camera_jpeg

confirmation_store = receipt_tests.confirmation_store
confirmation_web = page_tests.confirmation_web

SCOPE = {"datasetId": "dataset", "clientGeneration": "generation", "accountId": "account",
         "ledgerId": "owner", "deviceId": "browser"}
AUTH = AuthContext(11, "account", "Owner", "owner", "Home", 7, "browser", "Browser", "owner", "app")
FACT_FIELDS = ("id", "public_id", "status", "merchant", "amount_cents", "original_amount_minor",
               "original_currency_code", "home_currency_code", "expense_time", "accounting_date", "fact_revision")


@pytest.fixture
def first_original_web(confirmation_store, confirmation_web, monkeypatch, tmp_path):
    client, options = confirmation_web
    client.app.include_router(web_originals.router)
    LedgerAuditLog.__table__.create(confirmation_store)
    state = SimpleNamespace(auth=AUTH, options=options, client=client, engine=confirmation_store,
                            uploads=tmp_path / "uploads")

    def local(request: Request):
        request.state.web_session_auth = state.auth

    @client.app.exception_handler(AppError)
    async def error(_request, exc):
        return JSONResponse({"error": exc.error, "message": exc.message}, status_code=exc.status_code)

    client.app.dependency_overrides[web_originals.LocalOnly.dependency] = local
    monkeypatch.setattr(web_originals, "_list_ledger_options", lambda db: options)
    monkeypatch.setattr(web_originals, "_resolve_selected_ledger_id", lambda *args, **kwargs: "owner")
    monkeypatch.setattr(manual_expense_draft_presenter, "manual_draft_scope", lambda *args: SCOPE)
    monkeypatch.setattr(original_command_service, "lock_and_revalidate_mutation_actor", lambda *args, **kwargs: None)
    monkeypatch.setattr(original_command_service, "authorize_currency_metadata_write", lambda db: None)
    monkeypatch.setattr(original_command_service, "retain_publication", lambda *args: None)
    monkeypatch.setattr(file_service, "get_settings", lambda: SimpleNamespace(upload_dir=state.uploads,
                                                                            max_upload_size_bytes=1024 * 1024))
    with Session(state.engine) as db:
        expense = db.get(Expense, 42)
        expense.source, expense.status, expense.fact_revision = "手动记账", "confirmed", 1
        db.commit()
    return state


def _attach(case, *, key="a" * 32, version=4, scope=SCOPE, data=None):
    return case.client.post("/web/expenses/42/original/attach", params={"ledger_id": "owner",
        "draft_scope": json.dumps(scope), "idempotency_key": key, "expected_row_version": version},
        files={"file": ("camera.jpg", _camera_jpeg() if data is None else data, "image/jpeg")},
        headers={"Accept": "application/json"})


def _facts(case):
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        return tuple(getattr(row, name) for name in FACT_FIELDS)


def test_first_attachment_page_offers_optional_same_bill_action_only_to_writer(first_original_web):
    case = first_original_web
    response = case.client.get("/web/expenses/42/original?ledger_id=owner")
    assert response.status_code == 200, response.text
    assert "添加到这笔账单" in response.text and "/web/expenses/42/original/attach?" in response.text
    assert "没有小票也可以记账" in response.text
    case.options[0].role = "viewer"
    response = case.client.get("/web/expenses/42/original?ledger_id=owner")
    assert response.status_code == 200 and "/original/attach?" not in response.text


def test_first_original_is_private_admitted_evidence_on_same_bill_and_replay_is_immutable(first_original_web):
    case = first_original_web
    before = _facts(case)
    response = _attach(case)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ack"] == {"scope": SCOPE, "clientRef": "a" * 32}
    receipt = result["receipt"]
    assert (receipt["operation"], receipt["expense_id"], receipt["row_version"]) == ("attach_original", 42, 5)
    assert _facts(case) == before
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        source = file_service.resolve_upload_path_for_tenant(row.image_path, "owner")
        admitted = source.read_bytes()
        assert b"PrivateCameraIdentity" not in admitted
        assert admitted != _camera_jpeg()
        assert row.image_hash == receipt["sha256"] == hashlib.sha256(admitted).hexdigest()
        audit = db.scalar(select(LedgerAuditLog))
        assert (audit.action, audit.actor_account_id, audit.resource_public_id) == ("original_attached", 11, row.public_id)
        assert json.loads(audit.detail)["basis"] == "first_association"
        row.merchant, row.amount_cents, row.row_version = "后来修改", 9900, 9
        db.commit()
    source.unlink()
    replay = _attach(case)
    assert replay.json() == result
    assert not source.exists(), "accepted replay must not recreate later missing bytes"
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        assert (row.merchant, row.amount_cents, row.row_version) == ("后来修改", 9900, 9)
        assert len(db.scalars(select(Expense)).all()) == 1
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert len(db.scalars(select(LedgerAuditLog)).all()) == 1
    refused = _attach(case, key="b" * 32, version=9, data=_camera_jpeg(29))
    assert (refused.status_code, refused.json()["error"]) == (409, "original_already_associated")


def test_first_original_on_old_bill_gets_full_retention_without_changing_financial_dates(first_original_web, monkeypatch):
    case = first_original_web
    current = now_utc()
    old = current - timedelta(days=90)
    real_refresh = Session.refresh

    def refresh(db, row, *args, **kwargs):
        real_refresh(db, row, *args, **kwargs)
        # Reproduce PostgreSQL's aware UTC reads without changing SQLite facts.
        for field in ("confirmed_at", "image_replenished_at"):
            value = getattr(row, field)
            if value is not None and value.tzinfo is None:
                set_committed_value(row, field, value.replace(tzinfo=UTC))

    monkeypatch.setattr(Session, "refresh", refresh)
    settings = SimpleNamespace(delete_image_after_confirm=False, delete_image_after_days=30,
                               delete_rejected_after_days=30)
    monkeypatch.setattr(cleanup, "now_utc", lambda: current)
    monkeypatch.setattr(cleanup, "authorize_currency_metadata_write", lambda db: None)
    with Session(case.engine) as db:
        db.get(Expense, 42).confirmed_at = old
        db.commit()
    before = _facts(case)
    response = _attach(case)
    assert response.status_code == 200, response.text
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        source = file_service.resolve_upload_path_for_tenant(row.image_path, "owner")
        current += timedelta(days=2)
        result = cleanup.execute_attachment_cleanup(db, row, reason="confirmed_retention",
                                                     settings_provider=lambda: settings)
        assert result.deleted_images == 0 and source.is_file(), "newly attached evidence must get its retention period"
        assert row.attachment_cleanup_request is None and row.confirmed_at.replace(tzinfo=UTC) == old
        current += timedelta(days=30)
        result = cleanup.execute_attachment_cleanup(db, row, reason="confirmed_retention",
                                                     settings_provider=lambda: settings)
        assert result.deleted_images == 1 and not source.exists()
        assert row.image_deleted_at is not None and row.confirmed_at.replace(tzinfo=UTC) == old
    assert _facts(case) == before


@pytest.mark.parametrize("refusal", ["binding", "viewer", "stale", "invalid_image", "old_digest"])
def test_first_association_refusals_leave_no_file_fact_or_receipt(first_original_web, refusal):
    case = first_original_web
    args = {
        "binding": {"scope": {**SCOPE, "deviceId": "old-browser"}},
        "stale": {"version": 3},
        "invalid_image": {"data": b"not an image"},
    }.get(refusal, {})
    if refusal == "viewer":
        case.auth = replace(AUTH, role="viewer")
        case.options[0].role = "viewer"
    if refusal == "old_digest":
        with Session(case.engine) as db:
            db.get(Expense, 42).image_hash = "f" * 64
            db.commit()
    before = _facts(case)
    response = _attach(case, **args)
    assert response.status_code in (400, 403, 409), response.text
    assert _facts(case) == before
    assert not list(case.uploads.rglob("*.*"))
    with Session(case.engine) as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None
        assert db.scalar(select(LedgerAuditLog)) is None


@pytest.mark.parametrize("committed", [False, True])
def test_attachment_receipt_and_bytes_survive_only_an_accepted_transaction(first_original_web, monkeypatch, committed):
    case = first_original_web
    real_commit = Session.commit

    def fail(db):
        if committed:
            real_commit(db)
        raise SQLAlchemyError("injected uncertain commit")

    monkeypatch.setattr(Session, "commit", fail)
    with pytest.raises(SQLAlchemyError, match="injected uncertain commit"):
        _attach(case)
    monkeypatch.setattr(Session, "commit", real_commit)
    with Session(case.engine) as db:
        row, claim = db.get(Expense, 42), db.scalar(select(ApiIdempotencyKey))
        assert bool(row.image_path) is committed and bool(claim) is committed
        if committed:
            assert file_service.resolve_upload_path_for_tenant(row.image_path, "owner").is_file()
    # Uncertain commits retain staged bytes for the existing orphan owner; only
    # matching replay may resolve acceptance. No local guess deletes a published file.
    response = _attach(case)
    assert response.status_code == 200, response.text
    with Session(case.engine) as db:
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert db.get(Expense, 42).row_version == 5


def test_refused_receipt_rolls_back_first_reference_and_removes_unpublished_bytes(first_original_web, monkeypatch):
    case = first_original_web
    def refuse(*args, **kwargs):
        raise SQLAlchemyError("receipt unavailable")
    monkeypatch.setattr(original_command_service, "mark_idempotency_succeeded", refuse)
    with pytest.raises(SQLAlchemyError, match="receipt unavailable"):
        _attach(case)
    with Session(case.engine) as db:
        row = db.get(Expense, 42)
        assert (row.image_path, row.image_hash, row.row_version) == (None, None, 4)
        assert db.scalar(select(ApiIdempotencyKey)) is None
        assert db.scalar(select(LedgerAuditLog)) is None
    assert not list(case.uploads.rglob("*.jpg"))
