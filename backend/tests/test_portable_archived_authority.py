"""An archived owner can take data away without reopening ordinary ledger access."""

from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.models import AuthToken, Ledger, LedgerMember
from app.services import portable_export_service as service
from app.services.identity_service import authenticate_session_token
from app.services.time_service import now_utc
from tests.test_original_attachment_api import _bill, _financial_snapshot
from tests.test_portable_export_http import _assert_bill_and_unverified_original

pytestmark = pytest.mark.real_db


def _archive(identity):
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.app_headers["Authorization"].removeprefix("Bearer "), {"app"})
        ledger = db.scalar(select(Ledger).where(Ledger.ledger_id == auth.ledger_id))
        ledger.archived_at = now_utc()
        db.commit()
        return auth


def test_owner_with_no_active_ledger_downloads_records_and_original_without_switching(client, identity):
    expense_id, _, source = _bill(client, identity, legacy=True)
    before = _financial_snapshot(expense_id)
    auth = _archive(identity)
    headers = identity.app_headers
    assert client.get("/api/ledgers", headers=headers).json()["ledgers"] == []
    choices = client.get("/api/exports/ledgers", headers=headers)
    assert choices.status_code == 200, choices.text
    assert [(row["ledger_id"], row["role"]) for row in choices.json()["ledgers"]] == [(auth.ledger_id, "owner")]
    assert choices.json()["ledgers"][0]["archived_at"]
    downloaded = client.get("/api/exports/portable", headers=headers, params={"ledger_id": auth.ledger_id})
    _assert_bill_and_unverified_original(downloaded, expense_id, source.read_bytes())
    assert client.get("/api/auth/check", headers=headers).status_code == 403
    assert client.get("/api/exports/portable", headers=identity.gray_app_headers,
        params={"ledger_id": auth.ledger_id}).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(Ledger.archived_at).where(Ledger.ledger_id == auth.ledger_id)) is not None
        token = db.get(AuthToken, auth.credential_id)
        assert (token.ledger_id, token.account_id, token.device_id, token.token_hash) == (
            auth.ledger_id, auth.account_id, auth.device_id, auth.credential_hash)
    assert _financial_snapshot(expense_id) == before


@pytest.mark.parametrize("role,disabled", [("member", False), ("viewer", False), ("owner", True)])
def test_archived_nonowners_and_disabled_members_cannot_list_or_download(client, identity, role, disabled):
    auth = _archive(identity)
    with SessionLocal() as db:
        member = db.scalar(select(LedgerMember).where(LedgerMember.ledger_id == auth.ledger_id,
            LedgerMember.account_id == auth.account_id))
        member.role = role
        member.disabled_at = now_utc() if disabled else None
        db.commit()
    assert client.get("/api/exports/ledgers", headers=identity.app_headers).json()["ledgers"] == []
    assert client.get("/api/exports/portable", headers=identity.app_headers,
        params={"ledger_id": auth.ledger_id}).status_code == 403


def test_loss_of_archived_owner_during_generation_discards_completed_archive(identity, monkeypatch):
    auth = _archive(identity)
    archive_writer = service.create_portable_archive
    finished = []

    def lose_ownership_after_archive(**kwargs):
        archive = archive_writer(**kwargs)
        finished.append(archive.path)
        with ZipFile(archive.path) as package:
            assert "records/ledgers.jsonl" in package.namelist()
        with SessionLocal() as writer:
            member = writer.scalar(select(LedgerMember).where(LedgerMember.ledger_id == auth.ledger_id,
                LedgerMember.account_id == auth.account_id))
            member.role = "member"
            writer.commit()
        return archive

    monkeypatch.setattr(service, "create_portable_archive", lose_ownership_after_archive)
    with SessionLocal() as db, pytest.raises(AppError) as caught:
        service.create_portable_ledger_export(db, auth=auth)
    assert caught.value.error == "ledger_forbidden"
    assert len(finished) == 1 and not finished[0].parent.exists()
