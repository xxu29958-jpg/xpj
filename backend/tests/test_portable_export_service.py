"""Actual PostgreSQL snapshot, identity and lifecycle qualification for exports."""

import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.errors import AppError
from app.models import AuthToken, Expense, LedgerMember
from app.services import portable_export_service as service
from app.services.currency_binding_service import authorize_currency_metadata_write
from app.services.identity_service import authenticate_session_token
from app.services.time_service import now_utc

pytestmark = pytest.mark.real_db


def _auth(identity):
    with SessionLocal() as db:
        return authenticate_session_token(db, identity.app_headers["Authorization"].removeprefix("Bearer "), {"app"})


def _records(package, name):
    return [json.loads(line) for line in package.read(f"records/{name}.jsonl").splitlines()]


def _expense(auth, **values):
    with SessionLocal() as db:
        authorize_currency_metadata_write(db)
        expense = Expense(tenant_id=auth.ledger_id, amount_cents=1200, merchant="Before", **values)
        db.add(expense)
        db.commit()
        return expense.id


def test_export_reads_one_snapshot_and_does_not_commit_its_callers_work(identity, monkeypatch):
    auth = _auth(identity)
    expense_id = _expense(auth)
    archive_writer = service.create_portable_archive
    validate = service.revalidate_session_context
    snapshot_settings = []

    def observe_read_transaction(db, auth):
        snapshot_settings.append((db.scalar(select(func.current_setting("transaction_read_only"))),
            db.scalar(select(func.current_setting("transaction_isolation")))))
        return validate(db, auth)

    def change_after_snapshot(**kwargs):
        # This separate commit happens after the snapshot's identity query and
        # before any record collection is consumed. Both expense SELECTs must
        # still see the original row (one for records, one for original index).
        with SessionLocal() as writer:
            authorize_currency_metadata_write(writer)
            row = writer.get(Expense, expense_id)
            row.merchant = "Concurrent change"
            writer.add(Expense(tenant_id=auth.ledger_id, amount_cents=999, merchant="Later"))
            writer.commit()
        return archive_writer(**kwargs)

    monkeypatch.setattr(service, "create_portable_archive", change_after_snapshot)
    monkeypatch.setattr(service, "revalidate_session_context", observe_read_transaction)
    with SessionLocal() as caller:
        caller.add(Expense(tenant_id=auth.ledger_id, amount_cents=111, merchant="Uncommitted"))
        with service.create_portable_ledger_export(caller, auth=auth) as archive, ZipFile(archive.path) as package:
            rows = _records(package, "expenses")
            assert [(row["id"], row["merchant"], row["status"]) for row in rows] == [(expense_id, "Before", "pending")]
            originals = [json.loads(line) for line in package.read("originals.jsonl").splitlines()]
            assert [row["expense_id"] for row in originals] == [expense_id]
            assert json.loads(package.read("manifest.json"))["records_complete"] is True
        assert len(caller.new) == 1
        assert not archive.path.exists()
    with SessionLocal() as db:
        assert set(db.scalars(select(Expense.merchant))) == {"Concurrent change", "Later"}
        assert db.scalar(select(func.current_setting("transaction_read_only"))) == "off"
    assert snapshot_settings[0] == ("on", "repeatable read")
    assert snapshot_settings[-1][0] == "off"


@pytest.mark.parametrize("change,error", [("membership", "ledger_forbidden"), ("role", "permission_denied"),
    ("credential", "invalid_token"), ("binding", "invalid_token"), ("scope", "invalid_token")])
def test_export_rechecks_live_read_authority_before_opening_archive(identity, monkeypatch, change, error):
    auth = _auth(identity)
    with SessionLocal() as writer:
        member = writer.scalar(select(LedgerMember).where(LedgerMember.ledger_id == auth.ledger_id,
            LedgerMember.account_id == auth.account_id))
        if change == "membership":
            member.disabled_at = now_utc()
        if change == "role":
            member.role = "viewer"
        if change == "credential":
            token = writer.get(AuthToken, auth.credential_id)
            token.revoked_at, token.grace_until = now_utc(), None
        if change == "binding":
            auth = replace(auth, device_public_id="different-device")
        if change == "scope":
            auth = replace(auth, scope="upload")
        writer.commit()

    def unexpected_archive(**_kwargs):
        pytest.fail("Authorization failure must not read financial records or originals")

    monkeypatch.setattr(service, "create_portable_archive", unexpected_archive)
    with SessionLocal() as db, pytest.raises(AppError) as caught:
        service.create_portable_ledger_export(db, auth=auth)
    assert caught.value.error == error


def test_revocation_during_export_discards_finished_package_before_download(identity, monkeypatch):
    auth = _auth(identity)
    _expense(auth)
    archive_writer = service.create_portable_archive
    finished = []

    def revoke_after_archive(**kwargs):
        archive = archive_writer(**kwargs)
        finished.append(archive.path)
        with SessionLocal() as writer:
            token = writer.get(AuthToken, auth.credential_id)
            token.revoked_at, token.grace_until = now_utc(), None
            writer.commit()
        return archive

    monkeypatch.setattr(service, "create_portable_archive", revoke_after_archive)
    with SessionLocal() as db, pytest.raises(AppError) as caught:
        service.create_portable_ledger_export(db, auth=auth)
    assert caught.value.error == "invalid_token"
    assert len(finished) == 1 and not finished[0].parent.exists()
