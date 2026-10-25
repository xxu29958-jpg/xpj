"""First attachment uses the real Web command, PostgreSQL receipt and admitted file.

The browser identity is supplied at the HTTP boundary; credential fences,
financial facts, CAS, receipt settlement, publication locks and bytes are real.
"""
import hashlib
import json
import re
from dataclasses import replace
from datetime import timedelta
from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import ApiIdempotencyKey, Expense, LedgerAuditLog
from app.services import attachment_cleanup_service as cleanup
from app.services import file_service, original_command_service
from app.services.time_service import now_utc
from tests._infra.assets import _camera_jpeg
from tests.original_test_support import SCOPE, _attach, _facts
from tests.original_test_support import first_original_web as first_original_web
from tests.web_expense_fact_test_support import confirmation_store as confirmation_store
from tests.web_expense_fact_test_support import confirmation_web as confirmation_web


@pytest.mark.parametrize("status,fragment", [("pending", 0), ("pending", 1), ("confirmed", 0)])
def test_first_attachment_page_offers_optional_same_bill_action_only_to_writer(first_original_web, status, fragment):
    case = first_original_web
    with case.session_factory() as db:
        db.get(Expense, 42).status = status
        db.commit()
    origin = {"ledger_id": "owner", "return_to": "search", "return_query": "咖啡 & 茶"}
    detail = case.client.get("/web/expenses/42/edit", params={**origin, "fragment": fragment})
    assert detail.status_code == 200, detail.text
    links = [unescape(href) for href in re.findall(r'<a\b[^>]*href="([^"]+)"', detail.text)]
    original_links = [href for href in links if urlsplit(href).path == "/web/expenses/42/original"]
    assert len(original_links) == (2 if status == "pending" else 1)
    for original_href in original_links:
        assert parse_qs(urlsplit(original_href).query) == {key: [value] for key, value in origin.items()}
    response = case.client.get(original_href)
    assert response.status_code == 200, response.text
    assert "添加到这笔账单" in response.text and "/web/expenses/42/original/attach?" in response.text
    assert "没有小票也可以记账" in response.text
    links = [unescape(href) for href in re.findall(r'<a\b[^>]*href="([^"]+)"', response.text)]
    assert any(urlsplit(href).path == "/web/search" and parse_qs(urlsplit(href).query) == {
        "ledger_id": ["owner"], "q": ["咖啡 & 茶"]} for href in links)
    reload_href, = [href for href in links if urlsplit(href).path == "/web/expenses/42/original"]
    assert parse_qs(urlsplit(reload_href).query) == {key: [value] for key, value in origin.items()}
    assert case.client.get(reload_href).status_code == 200
    case.options[0].role = "viewer"
    response = case.client.get(original_href)
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
    with case.session_factory() as db:
        row = db.get(Expense, 42)
        source = file_service.resolve_upload_path_for_tenant(row.image_path, "owner")
        admitted = source.read_bytes()
        assert b"PrivateCameraIdentity" not in admitted
        assert admitted != _camera_jpeg()
        assert row.image_hash == receipt["sha256"] == hashlib.sha256(admitted).hexdigest()
        audit = db.scalar(select(LedgerAuditLog).where(LedgerAuditLog.resource_type == "expense"))
        assert (audit.action, audit.actor_account_id, audit.resource_public_id) == ("original_attached", case.original_auth.account_id, row.public_id)
        assert json.loads(audit.detail)["basis"] == "first_association"
        row.merchant, row.amount_cents, row.row_version = "后来修改", 9900, 9
        db.commit()
    source.unlink()
    replay = _attach(case)
    assert replay.json() == result
    assert not source.exists(), "accepted replay must not recreate later missing bytes"
    with case.session_factory() as db:
        row = db.get(Expense, 42)
        assert (row.merchant, row.amount_cents, row.row_version) == ("后来修改", 9900, 9)
        assert len(db.scalars(select(Expense)).all()) == 1
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert len(db.scalars(select(LedgerAuditLog).where(LedgerAuditLog.resource_type == "expense")).all()) == 1
    refused = _attach(case, key="b" * 32, version=9, data=_camera_jpeg(29))
    assert (refused.status_code, refused.json()["error"]) == (409, "original_already_associated")


def test_first_original_on_old_bill_gets_full_retention_without_changing_financial_dates(first_original_web, monkeypatch):
    case = first_original_web
    current = now_utc()
    old = current - timedelta(days=90)
    settings = SimpleNamespace(delete_image_after_confirm=False, delete_image_after_days=30,
                               delete_rejected_after_days=30)
    monkeypatch.setattr(cleanup, "now_utc", lambda: current)
    with case.session_factory() as db:
        db.get(Expense, 42).confirmed_at = old
        db.commit()
    before = _facts(case)
    response = _attach(case)
    assert response.status_code == 200, response.text
    with case.session_factory() as db:
        row = db.get(Expense, 42)
        source = file_service.resolve_upload_path_for_tenant(row.image_path, "owner")
        current += timedelta(days=2)
        result = cleanup.execute_attachment_cleanup(db, row, reason="confirmed_retention",
                                                     settings_provider=lambda: settings)
        assert result.deleted_images == 0 and source.is_file(), "newly attached evidence must get its retention period"
        assert row.attachment_cleanup_request is None and row.confirmed_at == old
        current += timedelta(days=30)
        result = cleanup.execute_attachment_cleanup(db, row, reason="confirmed_retention",
                                                     settings_provider=lambda: settings)
        assert result.deleted_images == 1 and not source.exists()
        assert row.image_deleted_at is not None and row.confirmed_at == old
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
        case.auth = replace(case.original_auth, role="viewer")
        case.options[0].role = "viewer"
    if refusal == "old_digest":
        with case.session_factory() as db:
            db.get(Expense, 42).image_hash = "f" * 64
            db.commit()
    before = _facts(case)
    response = _attach(case, **args)
    assert response.status_code in (400, 403, 409), response.text
    assert _facts(case) == before
    assert not list(case.uploads.rglob("*.*"))
    with case.session_factory() as db:
        assert db.get(Expense, 42).row_version == 4
        assert db.scalar(select(ApiIdempotencyKey)) is None
        assert db.scalar(select(LedgerAuditLog).where(LedgerAuditLog.resource_type == "expense")) is None


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
    with case.session_factory() as db:
        row, claim = db.get(Expense, 42), db.scalar(select(ApiIdempotencyKey))
        assert bool(row.image_path) is committed and bool(claim) is committed
        if committed:
            assert file_service.resolve_upload_path_for_tenant(row.image_path, "owner").is_file()
    # Uncertain commits retain staged bytes for the existing orphan owner; only
    # matching replay may resolve acceptance. No local guess deletes a published file.
    response = _attach(case)
    assert response.status_code == 200, response.text
    with case.session_factory() as db:
        assert len(db.scalars(select(ApiIdempotencyKey)).all()) == 1
        assert db.get(Expense, 42).row_version == 5


def test_refused_receipt_rolls_back_first_reference_and_removes_unpublished_bytes(first_original_web, monkeypatch):
    case = first_original_web
    def refuse(*args, **kwargs):
        raise SQLAlchemyError("receipt unavailable")
    monkeypatch.setattr(original_command_service, "mark_idempotency_succeeded", refuse)
    with pytest.raises(SQLAlchemyError, match="receipt unavailable"):
        _attach(case)
    with case.session_factory() as db:
        row = db.get(Expense, 42)
        assert (row.image_path, row.image_hash, row.row_version) == (None, None, 4)
        assert db.scalar(select(ApiIdempotencyKey)) is None
        assert db.scalar(select(LedgerAuditLog).where(LedgerAuditLog.resource_type == "expense")) is None
    assert not list(case.uploads.rglob("*.jpg"))
