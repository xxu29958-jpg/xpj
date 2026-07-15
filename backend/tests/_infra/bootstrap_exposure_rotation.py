"""Real-DB credential rotation after bootstrap listener exposure."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.services.identity_service as identity_service
from app.config import get_settings
from app.database import Base, SessionLocal, engine, init_db
from app.errors import AppError
from app.main import app
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    DeviceEnrollmentAttempt,
    Invitation,
    Ledger,
    LedgerMember,
    PairingCode,
    UploadLink,
)
from app.services.identity_service import (
    BootstrapResult,
    hash_pairing_code,
    hash_secret,
    rotate_exposed_bootstrap_credentials,
)
from app.services.session_lifecycle_service import (
    consume_pairing_code,
    derive_bootstrap_admin_token,
    derive_bootstrap_pairing_code,
    derive_bootstrap_upload_key,
    upload_link_expires_at,
)
from app.services.time_service import ensure_utc, now_utc
from tests._infra.bootstrap_exposure_setup import (
    _expire_exposed_upload_link,
    _ExposureWindow,
    _open_exposure_window,
    _seed_historical_revocation_evidence,
)
from tests._infra.bootstrap_recovery import (
    _VECTOR_ADMIN_TOKEN,
    _VECTOR_PAIRING_CODE,
    _VECTOR_SECRET,
    _VECTOR_UPLOAD_KEY,
    _enable_http_bootstrap,
)
from tests.pairing_test_support import pairing_payload


def _rotate_and_assert_initial_ttl(replacement_secret: str) -> BootstrapResult:
    rotation_started_at = now_utc()
    with SessionLocal() as db:
        rotated = rotate_exposed_bootstrap_credentials(
            db,
            exposed_secret=_VECTOR_SECRET,
            replacement_secret=replacement_secret,
        )
        assert rotated is not None
        assert rotated.admin_token == derive_bootstrap_admin_token(replacement_secret)
        assert rotated.upload_key == derive_bootstrap_upload_key(replacement_secret)
        assert rotated.pairing_code == derive_bootstrap_pairing_code(replacement_secret)
    rotation_finished_at = now_utc()
    with SessionLocal() as db:
        replacement_upload = db.query(UploadLink).filter(
            UploadLink.token_hash == hash_secret(derive_bootstrap_upload_key(replacement_secret))
        ).one()
        upload_expiration = ensure_utc(replacement_upload.expires_at)
        assert upload_expiration is not None
        assert upload_link_expires_at(rotation_started_at) <= upload_expiration
        assert upload_expiration <= upload_link_expires_at(rotation_finished_at)
    return rotated


def _assert_stale_pairing_cannot_be_consumed(exposure: _ExposureWindow) -> None:
    stale_consume = consume_pairing_code(
        exposure.stale_pairing_session,
        pairing_id=exposure.stale_pairing_id,
        expected_code_hash=exposure.stale_pairing_hash,
    )
    assert stale_consume == "expired", stale_consume
    exposure.stale_pairing_session.rollback()


def _assert_replacement_pairing_succeeds(replacement_secret: str) -> None:
    with TestClient(app) as client:
        replacement_pair = client.post(
            "/api/auth/pair",
            json=pairing_payload(
                derive_bootstrap_pairing_code(replacement_secret),
                device_name="Replacement Device",
            ),
        )
        assert replacement_pair.status_code == 200, replacement_pair.text


def _assert_exposed_invitation_is_rejected(invite_token: str) -> None:
    with TestClient(app) as client:
        preview = client.post(
            "/api/invitations/preview",
            json={"invite_token": invite_token},
        )
        assert preview.status_code == 400, preview.text
        assert preview.json()["error"] == "invitation_invalid"
        accept = client.post(
            "/api/invitations/accept",
            json={
                "invite_token": invite_token,
                "account_name": "Exposure Invitee",
                "device_name": "Exposure Invitee Device",
                "platform": "android",
            },
        )
        assert accept.status_code == 400, accept.text
        assert accept.json()["error"] == "invitation_invalid"


def _assert_descendant_revoked(
    db: Session,
    *,
    account_id: int,
    device_id: int,
    membership_id: int,
    session_hash: str,
) -> None:
    account = db.get(Account, account_id)
    device = db.get(Device, device_id)
    membership = db.get(LedgerMember, membership_id)
    session = db.query(AuthToken).filter(AuthToken.token_hash == session_hash).one()
    assert account is not None and account.disabled_at is not None
    assert device is not None and device.revoked_at is not None
    assert membership is not None and membership.disabled_at is not None
    assert session.revoked_at is not None
    assert session.grace_until is None


def _assert_exposed_principals_revoked(
    db: Session,
    *,
    exposed_session_hash: str,
    exposed_invite_token: str,
    exposure: _ExposureWindow,
    historical_at: datetime,
) -> None:
    exposed_session = db.query(AuthToken).filter(
        AuthToken.token_hash == exposed_session_hash
    ).one()
    assert ensure_utc(exposed_session.revoked_at) == ensure_utc(historical_at)
    assert exposed_session.grace_until is None
    exposed_device = db.get(Device, exposed_session.device_id)
    assert exposed_device is not None
    assert ensure_utc(exposed_device.revoked_at) == ensure_utc(historical_at)
    exposed_invitation = db.query(Invitation).filter(
        Invitation.token_hash == hash_secret(exposed_invite_token)
    ).one()
    assert exposed_invitation.used_at is None
    assert exposed_invitation.revoked_at is not None
    invited_account = db.get(Account, exposure.invited_account_id)
    invited_device = db.get(Device, exposure.invited_device_id)
    invited_membership = db.get(LedgerMember, exposure.invited_membership_id)
    invited_session = db.query(AuthToken).filter(
        AuthToken.token_hash == exposure.invited_session_hash
    ).one()
    assert invited_account is not None
    assert ensure_utc(invited_account.disabled_at) == ensure_utc(historical_at)
    assert invited_device is not None
    assert ensure_utc(invited_device.revoked_at) == ensure_utc(historical_at)
    assert invited_membership is not None
    assert ensure_utc(invited_membership.disabled_at) == ensure_utc(historical_at)
    assert invited_session.revoked_at is not None
    assert invited_session.grace_until is None
    _assert_descendant_revoked(
        db,
        account_id=exposure.transitive_account_id,
        device_id=exposure.transitive_device_id,
        membership_id=exposure.transitive_membership_id,
        session_hash=exposure.transitive_session_hash,
    )
    _assert_descendant_revoked(
        db,
        account_id=exposure.cross_account_id,
        device_id=exposure.cross_device_id,
        membership_id=exposure.cross_membership_id,
        session_hash=exposure.cross_session_hash,
    )
    transitive_pending = db.query(Invitation).filter(
        Invitation.token_hash
        == hash_secret(exposure.transitive_pending_invite_token)
    ).one()
    assert transitive_pending.used_at is None
    assert transitive_pending.revoked_at is not None
    cross_ledger = db.query(Ledger).filter(
        Ledger.ledger_id == exposure.cross_ledger_id
    ).one()
    assert cross_ledger.archived_at is not None


def _assert_unrelated_principal_untouched(db: Session, exposure: _ExposureWindow) -> None:
    unrelated_account = db.get(Account, exposure.unrelated_account_id)
    unrelated_device = db.get(Device, exposure.unrelated_device_id)
    unrelated_membership = db.get(LedgerMember, exposure.unrelated_membership_id)
    unrelated_session = db.query(AuthToken).filter(
        AuthToken.token_hash == exposure.unrelated_session_hash
    ).one()
    assert unrelated_account is not None and unrelated_account.disabled_at is None
    assert unrelated_device is not None and unrelated_device.revoked_at is None
    assert unrelated_membership is not None and unrelated_membership.disabled_at is None
    assert unrelated_session.revoked_at is None


def _assert_replacement_principal_recovered(
    db: Session,
    *,
    replacement_secret: str,
    exposure: _ExposureWindow,
) -> None:
    assert db.get(BootstrapSecretConsumption, hash_secret(replacement_secret)) is not None
    replacement_pairing = db.query(PairingCode).filter(
        PairingCode.code_hash
        == hash_pairing_code(derive_bootstrap_pairing_code(replacement_secret))
    ).one()
    assert replacement_pairing.used_at is None
    assert ensure_utc(replacement_pairing.expires_at) > now_utc()
    recovered_ledger = db.query(Ledger).filter(
        Ledger.ledger_id == exposure.ledger_id
    ).one()
    recovered_owner = db.get(LedgerMember, exposure.bootstrap_membership_id)
    assert recovered_ledger.owner_account_id == exposure.bootstrap_account_id
    assert recovered_owner is not None
    assert recovered_owner.role == "owner"
    assert recovered_owner.disabled_at is None
    recovered = identity_service.bootstrap_owner(db, bootstrap_secret=replacement_secret)
    assert recovered.admin_token == derive_bootstrap_admin_token(replacement_secret)
    with pytest.raises(AppError) as exposed_error:
        identity_service.bootstrap_owner(db, bootstrap_secret=_VECTOR_SECRET)
    assert exposed_error.value.error == "invalid_bootstrap_secret"


def _assert_exposure_rotation_persisted(
    *,
    replacement_secret: str,
    exposed_session_hash: str,
    exposed_invite_token: str,
    exposure: _ExposureWindow,
    historical_at: datetime,
) -> None:
    with SessionLocal() as db:
        assert db.query(AuthToken).filter(
            AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN)
        ).count() == 0
        assert db.query(UploadLink).filter(
            UploadLink.token_hash == hash_secret(_VECTOR_UPLOAD_KEY)
        ).count() == 0
        exposed_pairing = db.query(PairingCode).filter(
            PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
        ).one()
        assert exposed_pairing.used_at is not None
        exposed_pairing_expiration = ensure_utc(exposed_pairing.expires_at)
        assert exposed_pairing_expiration is not None
        assert exposed_pairing_expiration <= now_utc()
        assert db.query(DeviceEnrollmentAttempt).filter(
            DeviceEnrollmentAttempt.pairing_code_id == exposed_pairing.id
        ).count() == 1
        _assert_exposed_principals_revoked(
            db,
            exposed_session_hash=exposed_session_hash,
            exposed_invite_token=exposed_invite_token,
            exposure=exposure,
            historical_at=historical_at,
        )
        _assert_unrelated_principal_untouched(db, exposure)
        _assert_replacement_principal_recovered(
            db,
            replacement_secret=replacement_secret,
            exposure=exposure,
        )


def _assert_valid_rotation_replay_preserves_expiry(
    *,
    replacement_secret: str,
    expected_result: object,
) -> None:
    replacement_upload_hash = hash_secret(derive_bootstrap_upload_key(replacement_secret))
    replacement_hash = hash_pairing_code(derive_bootstrap_pairing_code(replacement_secret))
    with SessionLocal() as db:
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        pairing = db.query(PairingCode).filter(PairingCode.code_hash == replacement_hash).one()
        original_upload_expiration = upload.expires_at
        original_pairing_expiration = pairing.expires_at
    with SessionLocal() as db:
        repeated = rotate_exposed_bootstrap_credentials(
            db,
            exposed_secret=_VECTOR_SECRET,
            replacement_secret=replacement_secret,
        )
        assert repeated is not None
        for field in (
            "account_name",
            "ledger_id",
            "ledger_name",
            "device_name",
            "admin_token",
            "upload_key",
            "upload_url_path",
            "pairing_code",
        ):
            assert getattr(repeated, field) == getattr(expected_result, field)
        assert repeated.pairing_expires_at == expected_result.pairing_expires_at
    with SessionLocal() as db:
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        pairing = db.query(PairingCode).filter(PairingCode.code_hash == replacement_hash).one()
        assert upload.revoked_at is None
        assert upload.expires_at == original_upload_expiration
        assert pairing.expires_at == original_pairing_expiration


def _assert_expired_rotation_replay_is_rejected(
    *,
    replacement_secret: str,
) -> None:
    replacement_upload_hash = hash_secret(derive_bootstrap_upload_key(replacement_secret))
    expired_at = now_utc() - timedelta(seconds=1)
    with SessionLocal() as db:
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        original_expiration = upload.expires_at
        upload.expires_at = expired_at
        db.commit()

    with SessionLocal() as db:
        with pytest.raises(AppError) as replay_error:
            rotate_exposed_bootstrap_credentials(
                db,
                exposed_secret=_VECTOR_SECRET,
                replacement_secret=replacement_secret,
                commit=False,
            )
        assert replay_error.value.error == "invalid_bootstrap_secret"
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        assert upload.expires_at == expired_at
        db.rollback()

    with SessionLocal() as db:
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        assert upload.expires_at == expired_at
        upload.expires_at = original_expiration
        db.commit()


def _assert_revoked_rotation_replay_is_rejected(*, replacement_secret: str) -> None:
    replacement_upload_hash = hash_secret(derive_bootstrap_upload_key(replacement_secret))
    with SessionLocal() as db:
        upload = db.query(UploadLink).filter(
            UploadLink.token_hash == replacement_upload_hash
        ).one()
        original_expiration = upload.expires_at
        revoked_at = now_utc()
        upload.revoked_at = revoked_at
        db.flush()

        with pytest.raises(AppError) as replay_error:
            rotate_exposed_bootstrap_credentials(
                db,
                exposed_secret=_VECTOR_SECRET,
                replacement_secret=replacement_secret,
                commit=False,
            )
        assert replay_error.value.error == "invalid_bootstrap_secret"
        assert upload.revoked_at == revoked_at
        assert upload.expires_at == original_expiration
        db.rollback()


def assert_exposed_secret_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    replacement_secret = "ticketbox-bootstrap-replacement-2026-07-10"
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()

    exposure = None
    try:
        exposure = _open_exposure_window(monkeypatch)
        _expire_exposed_upload_link()
        historical_at = _seed_historical_revocation_evidence(exposure)
        rotated = _rotate_and_assert_initial_ttl(replacement_secret)

        _assert_valid_rotation_replay_preserves_expiry(
            replacement_secret=replacement_secret,
            expected_result=rotated,
        )
        _assert_expired_rotation_replay_is_rejected(
            replacement_secret=replacement_secret,
        )
        _assert_revoked_rotation_replay_is_rejected(replacement_secret=replacement_secret)
        _assert_stale_pairing_cannot_be_consumed(exposure)
        _assert_exposed_invitation_is_rejected(exposure.exposed_invite_token)
        _assert_exposed_invitation_is_rejected(
            exposure.transitive_pending_invite_token
        )
        _assert_exposure_rotation_persisted(
            replacement_secret=replacement_secret,
            exposed_session_hash=exposure.exposed_session_hash,
            exposed_invite_token=exposure.exposed_invite_token,
            exposure=exposure,
            historical_at=historical_at,
        )
        _assert_replacement_pairing_succeeds(replacement_secret)
    finally:
        if exposure is not None:
            exposure.stale_pairing_session.close()
        get_settings.cache_clear()
