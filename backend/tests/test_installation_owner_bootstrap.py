from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import app.services.identity_service._installation_bootstrap as _installation_bootstrap
import app.services.identity_service._installation_claim as _installation_claim
import app.services.identity_service._installation_recovery as _installation_recovery
from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import (
    Account,
    AuthToken,
    BootstrapSecretConsumption,
    Device,
    InstallationOwnerClaim,
    PairingCode,
    UploadLink,
)
from app.services.identity_service import rotate_exposed_bootstrap_credentials
from app.services.session_lifecycle_service import hash_secret
from app.services.time_service import ensure_utc, now_utc
from tests.pairing_test_support import pairing_payload

pytestmark = pytest.mark.real_db

_SECRET = "installation-owner-bootstrap-secret-000000000000000001"
_REPLACEMENT = "installation-owner-bootstrap-secret-000000000000000002"
_OPERATION_ID = "install-op:stable-0001"
_INSTALLATION_ID = "install-id:machine-0001"


@contextmanager
def _bootstrap_client(monkeypatch: pytest.MonkeyPatch, secret: str):
    monkeypatch.setenv("ENABLE_HTTP_BOOTSTRAP", "true")
    monkeypatch.setenv("HTTP_BOOTSTRAP_SECRET", secret)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        get_settings.cache_clear()


def _post(client: TestClient, secret: str, **overrides):
    body = {
        "operation_id": _OPERATION_ID,
        "installation_id": _INSTALLATION_ID,
        "account_name": "我",
        "ledger_name": "我的小票夹",
        "device_name": "Windows 安装来源",
        **overrides,
    }
    return client.post(
        "/api/bootstrap/installation-owner",
        headers={"X-Bootstrap-Secret": secret},
        json=body,
    )


def test_installation_owner_bootstrap_requires_secret_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        response = client.post(
            "/api/bootstrap/installation-owner",
            json={
                "operation_id": _OPERATION_ID,
                "installation_id": _INSTALLATION_ID,
            },
        )
    assert response.status_code == 401
    with SessionLocal() as db:
        assert db.query(InstallationOwnerClaim).count() == 0
        assert db.query(BootstrapSecretConsumption).count() == 0


def test_installation_owner_bootstrap_issues_pairing_only_and_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        first = _post(client, _SECRET)
        second = _post(client, _SECRET)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    payload = first.json()
    assert payload == second.json()
    assert payload["contract"] == "ticketbox-installation-owner-pairing-v1"
    assert payload["operation_id"] == _OPERATION_ID
    assert payload["installation_id"] == _INSTALLATION_ID
    assert payload["pairing_code"].isdigit()
    assert len(payload["pairing_code"]) == 8
    assert payload["claim_generation"] == 1
    assert "admin_token" not in payload
    assert "upload_key" not in payload

    with SessionLocal() as db:
        assert db.query(InstallationOwnerClaim).count() == 1
        assert db.query(BootstrapSecretConsumption).count() == 1
        assert db.query(PairingCode).count() == 1
        assert db.query(AuthToken).count() == 0
        assert db.query(UploadLink).count() == 0


def test_installation_owner_replay_rejects_changed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        assert _post(client, _SECRET).status_code == 200
        changed = _post(client, _SECRET, ledger_name="另一账本")
    assert changed.status_code == 401
    assert changed.json()["error"] == "invalid_bootstrap_secret"
    assert _SECRET not in changed.text


def test_installation_owner_rejects_foreign_operation_without_new_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        assert _post(client, _SECRET).status_code == 200
        foreign = _post(client, _SECRET, operation_id="install-op:foreign")
    assert foreign.status_code == 409
    assert foreign.json()["error"] == "bootstrap_already_initialized"
    with SessionLocal() as db:
        assert db.query(InstallationOwnerClaim).count() == 1
        assert db.query(BootstrapSecretConsumption).count() == 1
        assert db.query(PairingCode).count() == 1


def test_installation_owner_rejects_fully_foreign_second_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        assert _post(client, _SECRET).status_code == 200
    with _bootstrap_client(monkeypatch, _REPLACEMENT) as client:
        foreign = _post(
            client,
            _REPLACEMENT,
            operation_id="install-op:foreign",
            installation_id="install-id:foreign-machine",
        )
    assert foreign.status_code == 409
    assert foreign.json()["error"] == "bootstrap_already_initialized"
    with SessionLocal() as db:
        assert db.query(InstallationOwnerClaim).count() == 1
        assert db.query(BootstrapSecretConsumption).count() == 1
        assert db.query(PairingCode).count() == 1


def test_expired_pairing_is_replaced_under_same_operation_and_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        first = _post(client, _SECRET)
        assert first.status_code == 200, first.text
        first_payload = first.json()

        with SessionLocal() as db:
            claim = db.get(InstallationOwnerClaim, _OPERATION_ID)
            assert claim is not None
            first_pairing_id = claim.pairing_code_id
            first_pairing = db.get(PairingCode, first_pairing_id)
            assert first_pairing is not None
            first_pairing.expires_at = now_utc() - timedelta(seconds=1)
            db.commit()

        replay = _post(client, _SECRET)

    assert replay.status_code == 200, replay.text
    payload = replay.json()
    assert payload["operation_id"] == _OPERATION_ID
    assert payload["installation_id"] == _INSTALLATION_ID
    assert payload["claim_generation"] == 2
    assert payload["pairing_code"] != first_payload["pairing_code"]

    with SessionLocal() as db:
        claim = db.get(InstallationOwnerClaim, _OPERATION_ID)
        assert claim is not None
        assert claim.generation == 2
        assert claim.pairing_code_id != first_pairing_id
        retired = db.get(PairingCode, first_pairing_id)
        current = db.get(PairingCode, claim.pairing_code_id)
        assert retired is not None and retired.revoked_at is not None
        assert current is not None and current.revoked_at is None
        assert ensure_utc(retired.expires_at) <= ensure_utc(retired.revoked_at)
        assert db.query(PairingCode).count() == 2


def test_installation_owner_failure_rolls_back_secret_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with SessionLocal() as db:
        account_count_before = db.query(Account).count()

    def fail_pairing_candidate(*_args, **_kwargs):
        raise AppError(
            "installation_pairing_collision",
            "injected pairing allocation failure",
            status_code=503,
        )

    assert _installation_bootstrap.installation_claim is _installation_claim
    monkeypatch.setattr(_installation_claim, "pairing_candidate", fail_pairing_candidate)
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        failed = _post(client, _SECRET)
    assert failed.status_code == 503
    assert failed.json()["error"] == "installation_pairing_collision"
    with SessionLocal() as db:
        assert db.query(InstallationOwnerClaim).count() == 0
        assert db.query(BootstrapSecretConsumption).count() == 0
        assert db.query(PairingCode).count() == 0
        assert db.query(Account).count() == account_count_before


def test_legacy_credential_bundle_cannot_follow_installation_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        assert _post(client, _SECRET).status_code == 200
    with _bootstrap_client(monkeypatch, _REPLACEMENT) as client:
        legacy = client.post(
            "/api/bootstrap/owner",
            headers={"X-Bootstrap-Secret": _REPLACEMENT},
            json={},
        )
    assert legacy.status_code == 409
    assert legacy.json()["error"] == "bootstrap_already_initialized"
    with SessionLocal() as db:
        assert db.query(AuthToken).count() == 0
        assert db.query(UploadLink).count() == 0
        assert db.get(BootstrapSecretConsumption, hash_secret(_REPLACEMENT)) is None


def test_listener_exposure_rotation_preserves_operation_and_revokes_only_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _bootstrap_client(monkeypatch, _SECRET) as client:
        created = _post(client, _SECRET)
        assert created.status_code == 200, created.text
        paired = client.post(
            "/api/auth/pair",
            json=pairing_payload(created.json()["pairing_code"]),
        )
        assert paired.status_code == 200, paired.text

    with SessionLocal() as db:
        claim_before = db.get(InstallationOwnerClaim, _OPERATION_ID)
        assert claim_before is not None
        bootstrap_device_id = claim_before.device_id
        paired_device = (
            db.query(Device)
            .filter(Device.public_id == paired.json()["device_public_id"])
            .one()
        )
        paired_device_id = paired_device.id
        rotated = rotate_exposed_bootstrap_credentials(
            db,
            exposed_secret=_SECRET,
            replacement_secret=_REPLACEMENT,
        )
        assert rotated is not None
        assert rotated.operation_id == _OPERATION_ID
        assert rotated.installation_id == _INSTALLATION_ID
        handled, replayed = _installation_recovery.rotate_installation_owner_claim(
            db,
            exposed_secret=_SECRET,
            replacement_secret=_REPLACEMENT,
        )
        assert handled and replayed == rotated

    with SessionLocal() as db:
        claim = db.get(InstallationOwnerClaim, _OPERATION_ID)
        assert claim is not None
        assert claim.generation == 2
        assert claim.active_secret_hash == hash_secret(_REPLACEMENT)
        assert db.get(Device, bootstrap_device_id).revoked_at is None
        assert db.get(Device, paired_device_id).revoked_at is not None
        assert all(
            token.revoked_at is not None
            for token in db.query(AuthToken).filter(AuthToken.device_id == paired_device_id)
        )
        assert db.query(UploadLink).count() == 0

    with _bootstrap_client(monkeypatch, _REPLACEMENT) as client:
        replay = _post(client, _REPLACEMENT)
    assert replay.status_code == 200, replay.text
    assert replay.json()["operation_id"] == _OPERATION_ID
    assert replay.json()["claim_generation"] == 2
