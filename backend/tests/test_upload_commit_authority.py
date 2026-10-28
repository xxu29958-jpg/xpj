"""Real upload consumers keep the original actor valid through acceptance."""

from __future__ import annotations

import hashlib
import html
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from api_contract_helpers import _stored_upload_files
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.database import SessionLocal
from app.main import app
from app.models import Account, ApiIdempotencyKey, AuthToken, BackgroundTask, Device, Expense, LedgerMember
from app.routes import _upload_request
from app.routes.web_auth import SESSION_COOKIE_NAME
from app.services import admin_service, original_command_service
from app.services.admin_service import _devices as admin_devices
from app.services.expense_service import _enrichment_receipt
from app.services.file_service import resolve_upload_path_for_tenant
from app.services.identity_service import authenticate_session_token, hash_secret
from app.services.invitation_members import transfer_ledger_owner
from tests._infra.assets import PNG_BYTES
from tests._web_public_session_support import PUBLIC_HOST, mint_session, public_client


@contextmanager
def _original_upload(client, identity, consumer):
    key = "original-upload-commit-authority"
    files = {"file": ("original.png", PNG_BYTES, "image/png")}
    if consumer == "app":
        yield identity.app_token, lambda: client.post(
            "/api/app/upload-screenshot", files=files,
            headers={**identity.app_headers, "Idempotency-Key": key, "X-Timezone": "UTC"},
        )
        return
    token = mint_session(client, identity=identity)
    with closing(public_client()) as browser:
        browser.cookies.set(SESSION_COOKIE_NAME, token)
        page = browser.get("/web/pending?ledger_id=owner")
        assert page.status_code == 200, page.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        scope = re.search(r"data-expensereview-scope='([^']+)'", page.text)
        assert csrf is not None and scope is not None
        yield token, lambda: browser.post(
            "/web/pending/upload", files=files, data={"csrf_token": csrf.group(1)},
            params={"ledger_id": "owner", "timezone": "UTC", "idempotency_key": key,
                    "draft_scope": html.unescape(scope.group(1))},
            headers={"Origin": f"https://{PUBLIC_HOST}", "Accept": "application/json"},
            follow_redirects=False,
        )


def _device_public_id(token):
    with SessionLocal() as db:
        credential = db.scalar(select(AuthToken).where(AuthToken.token_hash == hash_secret(token)))
        assert credential is not None
        return db.get(Device, credential.device_id).public_id


def _revoke_device(identity, public_id):
    with SessionLocal() as db:
        auth = authenticate_session_token(db, identity.admin_token, {"admin"})
        admin_service.revoke_device(db, public_id=public_id, current_device_public_id=auth.device_public_id,
            auth=auth, actor_account_id=auth.account_id)


def _artifacts():
    with SessionLocal() as db:
        counts = tuple(int(db.scalar(select(func.count()).select_from(model)) or 0)
                       for model in (Expense, BackgroundTask, ApiIdempotencyKey))
    return counts, _stored_upload_files()


@pytest.mark.real_db
@pytest.mark.parametrize("consumer", ["app", "web"])
def test_revocation_during_upload_read_refuses_all_new_artifacts(client, identity, monkeypatch, consumer):
    read = threading.Event()
    release = threading.Event()
    original_read = _upload_request.read_request_upload

    async def pause_after_read(*args, **kwargs):
        content = await original_read(*args, **kwargs)
        read.set()
        assert release.wait(timeout=10)
        return content

    monkeypatch.setattr(_upload_request, "read_request_upload", pause_after_read)
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    with _original_upload(client, identity, consumer) as (token, post):
        public_id = _device_public_id(token)
        before = _artifacts()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(post)
            try:
                assert read.wait(timeout=10)
                _revoke_device(identity, public_id)
            finally:
                release.set()
            response = future.result(timeout=15)
    assert (response.status_code, _artifacts()) == (401, before)
    assert response.json()["error"] == "invalid_token"


@pytest.mark.real_db
@pytest.mark.parametrize("consumer", ["app", "web"])
def test_upload_commit_keeps_actor_lock_until_receipt_is_durable(client, identity, monkeypatch, consumer):
    staged = threading.Event()
    release = threading.Event()
    revoke_waiting = threading.Event()
    revoke_finished = threading.Event()
    original_prepare = _upload_request.prepare_pending_expense_enrichment
    original_actor_lock = admin_devices.lock_and_revalidate_credential_mint_context

    def pause_after_stage(*args, **kwargs):
        prepared = original_prepare(*args, **kwargs)
        staged.set()
        assert release.wait(timeout=10)
        return prepared

    def observe_revoke_lock(*args, **kwargs):
        revoke_waiting.set()
        return original_actor_lock(*args, **kwargs)

    def revoke(public_id):
        _revoke_device(identity, public_id)
        revoke_finished.set()

    monkeypatch.setattr(_upload_request, "prepare_pending_expense_enrichment", pause_after_stage)
    monkeypatch.setattr(admin_devices, "lock_and_revalidate_credential_mint_context", observe_revoke_lock)
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    with _original_upload(client, identity, consumer) as (token, post):
        public_id = _device_public_id(token)
        with ThreadPoolExecutor(max_workers=2) as pool:
            upload = pool.submit(post)
            try:
                assert staged.wait(timeout=10)
                revocation = pool.submit(revoke, public_id)
                assert revoke_waiting.wait(timeout=10)
                assert not revoke_finished.wait(timeout=0.2)
            finally:
                release.set()
            response = upload.result(timeout=15)
            revocation.result(timeout=15)
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"] if consumer == "web" else response.json()
    counts, files = _artifacts()
    assert counts == (1, 1, 1) and len(files) == 1
    with SessionLocal() as db:
        expense = db.get(Expense, receipt["id"])
        task = db.scalar(select(BackgroundTask).where(BackgroundTask.public_id == receipt["enrichment_task_public_id"]))
        device = db.scalar(select(Device).where(Device.public_id == public_id))
        assert expense is not None and task.source_expense_id == expense.id
        assert task.initiated_by_account_id == device.account_id
        assert task.initiated_by_device_id == device.id
        assert device.revoked_at is not None


@pytest.mark.real_db
def test_upload_and_original_command_serialize_reused_key_without_deadlock(client, identity, monkeypatch):
    created = client.post("/api/expenses/manual", headers=identity.app_headers,
        json={"client_ref": str(uuid4()), "home_currency_code": "CNY", "amount_cents": 1234})
    assert created.status_code == 200, created.text
    expense_id = created.json()["id"]
    key_claimed = threading.Event()
    release_upload = threading.Event()
    original_lock_requested = threading.Event()
    original_lock_acquired = threading.Event()
    claim_upload_key = _upload_request.claim_idempotency_key
    lock_original_actor = original_command_service.lock_and_revalidate_mutation_actor

    def pause_after_key_claim(*args, **kwargs):
        claim = claim_upload_key(*args, **kwargs)
        key_claimed.set()
        assert release_upload.wait(timeout=10)
        return claim

    def observe_original_lock(*args, **kwargs):
        original_lock_requested.set()
        auth = lock_original_actor(*args, **kwargs)
        original_lock_acquired.set()
        return auth

    monkeypatch.setattr(_upload_request, "claim_idempotency_key", pause_after_key_claim)
    monkeypatch.setattr(original_command_service, "lock_and_revalidate_mutation_actor", observe_original_lock)
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    with _original_upload(client, identity, "app") as (_token, post), ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(post)
        try:
            assert key_claimed.wait(timeout=10)
            original = pool.submit(client.post, f"/api/expenses/{expense_id}/original/attach",
                headers={**identity.app_headers, "Idempotency-Key": "original-upload-commit-authority"},
                params={"expected_row_version": created.json()["row_version"]},
                files={"file": ("original.png", PNG_BYTES, "image/png")})
            assert original_lock_requested.wait(timeout=10)
            # Before the fix this owner acquires identity then waits on the key;
            # with consistent ordering it waits on identity until upload commits.
            original_lock_acquired.wait(timeout=0.2)
        finally:
            release_upload.set()
        accepted = upload.result(timeout=15)
        refused = original.result(timeout=15)
    assert accepted.status_code == 200, accepted.text
    assert refused.status_code == 422 and refused.json()["error"] == "idempotency_key_reused"
    with SessionLocal() as db:
        assert db.get(Expense, expense_id).image_path is None
    assert len(_stored_upload_files()) == 1


@pytest.mark.real_db
def test_loopback_upload_refuses_captured_owner_after_transfer_during_read(client, identity, monkeypatch):
    with SessionLocal() as db:
        target = Account(display_name="next upload owner")
        db.add(target)
        db.flush()
        member = LedgerMember(ledger_id="owner", account_id=target.id, role="member")
        db.add(member)
        db.commit()
        member_id = member.id
    read = threading.Event()
    release = threading.Event()
    original_read = _upload_request.read_request_upload

    async def pause_after_read(*args, **kwargs):
        content = await original_read(*args, **kwargs)
        read.set()
        assert release.wait(timeout=10)
        return content

    monkeypatch.setattr(_upload_request, "read_request_upload", pause_after_read)
    monkeypatch.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
    before = _artifacts()
    with (closing(TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50002))) as browser,
          ThreadPoolExecutor(max_workers=1) as pool):
        page = browser.get("/web/pending?ledger_id=owner")
        assert page.status_code == 200, page.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf is not None
        upload = pool.submit(browser.post, "/web/pending/upload",
            params={"ledger_id": "owner", "idempotency_key": "loopback-original-upload"},
            data={"csrf_token": csrf.group(1)},
            files={"file": ("original.png", PNG_BYTES, "image/png")},
            headers={"Accept": "application/json", "Origin": "http://127.0.0.1"}, follow_redirects=False)
        try:
            assert read.wait(timeout=10)
            with SessionLocal() as db:
                auth = authenticate_session_token(db, identity.admin_token, {"admin"})
                transfer_ledger_owner(db, ledger_id="owner", member_id=member_id,
                    requester_account_id=auth.account_id, auth=auth)
        finally:
            release.set()
        response = upload.result(timeout=15)
    assert (response.status_code, _artifacts()) == (403, before)
    assert response.json()["error"] == "permission_denied"


@pytest.mark.real_db
def test_accepted_upload_replay_releases_admission_before_waking_original_worker(client, identity, monkeypatch):
    headers = {**identity.app_headers, "Idempotency-Key": "queued-original-upload", "Content-Type": "image/png"}
    with monkeypatch.context() as admission:
        admission.setattr("app.services.background_task_executor.submit_task", lambda *_args, **_kwargs: None)
        first = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert first.status_code == 200, first.text
    before = _artifacts()
    original_hashes = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before[1]}
    original_lock = _enrichment_receipt.lock_bootstrap_owner_transaction

    def bounded_worker_lock(db):
        # Execute the real worker/owner on its own connection, but fail promptly
        # if receipt admission still holds a lock that prevents its progress.
        db.execute(text("SET LOCAL lock_timeout = '500ms'"))
        original_lock(db)

    monkeypatch.setattr(_enrichment_receipt, "lock_bootstrap_owner_transaction", bounded_worker_lock)
    monkeypatch.setenv("XPJ_BACKGROUND_TASK_INLINE", "1")
    replay = client.post("/api/app/upload-screenshot", headers=headers, content=PNG_BYTES)
    assert replay.status_code == 200 and replay.json() == first.json()
    after_counts, after_files = _artifacts()
    assert after_counts == before[0]
    with SessionLocal() as db:
        task = db.scalar(select(BackgroundTask).where(
            BackgroundTask.public_id == first.json()["enrichment_task_public_id"]))
        assert task.status == "completed"
        assert json.loads(task.result_summary_json)["outcome"] == "no_result"
        expense = db.get(Expense, first.json()["id"])
        assert expense.image_hash == first.json()["image_hash"]
        thumbnail = resolve_upload_path_for_tenant(expense.thumbnail_path, expense.tenant_id)
        assert thumbnail is not None and thumbnail.is_file()
        assert set(after_files) == set(before[1]) | {str(thumbnail)}
        assert {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in original_hashes} == original_hashes
