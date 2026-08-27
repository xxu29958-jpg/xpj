"""UploadLink commit-time revocation and expiry-extension races."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi import Request
from sqlalchemy import func, select

import app.routes._upload_request as upload_request_routes
import app.services.admin_service._upload_links as admin_upload_links
import app.services.identity_service._auth as identity_auth
from app.database import SessionLocal
from app.models import Expense, UploadLink
from app.services import admin_service
from app.services.file_service import SavedUpload
from app.services.identity_service import authenticate_session_token, hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests._infra.assets import PNG_BYTES
from tests._infra.client import make_test_client
from tests._infra.identity import TestIdentity


def _admin_auth(db, identity: TestIdentity):
    return authenticate_session_token(db, identity.admin_token, {"admin"})


def _post_shortcut_upload(upload_key: str):
    with make_test_client() as client:
        return client.post(
            f"/u/{upload_key}",
            headers={"Content-Type": "image/png"},
            content=PNG_BYTES,
        )


def _assert_inflight_upload_rechecks_revocation(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    file_saved = threading.Event()
    release_request = threading.Event()
    original_save = upload_request_routes.save_request_upload

    async def gated_save(
        request: Request,
        tenant_id: str,
        *,
        max_size_bytes: int | None = None,
    ) -> tuple[SavedUpload, dict[str, int]]:
        saved = await original_save(
            request,
            tenant_id,
            max_size_bytes=max_size_bytes,
        )
        file_saved.set()
        assert release_request.wait(timeout=5)
        return saved

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as pool:
        patch.setattr(upload_request_routes, "save_request_upload", gated_save)
        future = pool.submit(_post_shortcut_upload, identity.upload_key)
        assert file_saved.wait(timeout=5)
        try:
            with SessionLocal() as db:
                auth = _admin_auth(db, identity)
                link = db.scalar(
                    select(UploadLink).where(
                        UploadLink.token_hash == hash_secret(identity.upload_key)
                    )
                )
                assert link is not None
                admin_service.revoke_upload_link(
                    db,
                    public_id=link.public_id,
                    auth=auth,
                    actor_account_id=auth.account_id,
                )
        finally:
            release_request.set()
        response = future.result(timeout=10)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense)) == 0
    from api_contract_helpers import _stored_upload_files

    assert _stored_upload_files() == []


def _create_extend_target(identity: TestIdentity) -> tuple[str, str]:
    with SessionLocal() as db:
        auth = _admin_auth(db, identity)
        summary, secret = admin_service.create_upload_link(
            db,
            ledger_id="owner",
            admin_account_id=auth.account_id,
            default_timezone="Asia/Shanghai",
            auth=auth,
        )
        upload_key = secret.upload_url_path.split("?", maxsplit=1)[0].removeprefix(
            "/u/"
        )
        return summary.public_id, upload_key


def _extend_upload_link(identity: TestIdentity, public_id: str):
    with SessionLocal() as db:
        auth = _admin_auth(db, identity)
        return admin_service.extend_upload_link(
            db,
            public_id=public_id,
            auth=auth,
            actor_account_id=auth.account_id,
        )


def _authenticate_upload_link(upload_key: str):
    with SessionLocal() as db:
        return identity_auth.authenticate_upload_link(db, upload_key)


def _wait_until_expired(expires_at) -> None:
    expiration = ensure_utc(expires_at)
    assert expiration is not None
    while now_utc() <= expiration:
        time.sleep(0.02)


def _assert_extend_wins_before_expiry_revocation(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    public_id, upload_key = _create_extend_target(identity)
    with SessionLocal() as db:
        link = db.scalar(select(UploadLink).where(UploadLink.public_id == public_id))
        assert link is not None
        link.expires_at = now_utc() + timedelta(seconds=1)
        old_expiration = link.expires_at
        db.commit()

    extension_calculating = threading.Event()
    expiry_lock_requested = threading.Event()
    release_extension = threading.Event()
    original_expires_at = admin_upload_links.upload_link_expires_at
    original_auth_lock = identity_auth.lock_bootstrap_owner_transaction

    def gated_expires_at(base):
        extension_calculating.set()
        assert release_extension.wait(timeout=5)
        return original_expires_at(base)

    def observed_auth_lock(db) -> None:
        expiry_lock_requested.set()
        original_auth_lock(db)

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(admin_upload_links, "upload_link_expires_at", gated_expires_at)
        patch.setattr(identity_auth, "lock_bootstrap_owner_transaction", observed_auth_lock)
        extend = pool.submit(_extend_upload_link, identity, public_id)
        assert extension_calculating.wait(timeout=5)
        _wait_until_expired(old_expiration)
        authenticate = pool.submit(_authenticate_upload_link, upload_key)
        assert expiry_lock_requested.wait(timeout=5)
        time.sleep(0.1)
        assert not authenticate.done()
        release_extension.set()
        extended = extend.result(timeout=10)
        refreshed = authenticate.result(timeout=10)

    assert refreshed.scope == "upload"
    assert extended.expires_at is not None
    reported_expiration = datetime.fromisoformat(
        extended.expires_at.replace("Z", "+00:00")
    )
    with SessionLocal() as db:
        link = db.scalar(select(UploadLink).where(UploadLink.public_id == public_id))
        assert link is not None and link.revoked_at is None
        assert ensure_utc(link.expires_at) == ensure_utc(reported_expiration)
        assert ensure_utc(link.expires_at) > ensure_utc(old_expiration)


def assert_upload_link_commit_races_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    _assert_inflight_upload_rechecks_revocation(monkeypatch, identity)
    _assert_extend_wins_before_expiry_revocation(monkeypatch, identity)
