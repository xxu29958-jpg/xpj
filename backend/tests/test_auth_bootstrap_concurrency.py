from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import SessionLocal, engine, init_db
from app.database_model_registry import Base
from app.errors import AppError
from app.main import app
from app.models import AuthToken, PairingCode
from app.services.identity_service import (
    ReplacementCredentialCollisionError,
    hash_pairing_code,
    hash_secret,
    rotate_exposed_bootstrap_credentials,
)
from app.services.identity_service._bootstrap_exposure_guard import (
    assert_bootstrap_sensitive_mutation_allowed,
)
from app.services.session_credential_lock import lock_bootstrap_owner_transaction
from app.services.session_lifecycle_service import derive_bootstrap_pairing_code
from app.services.time_service import now_utc
from tests._infra.admin_mutation_concurrency import (
    STALE_ADMIN_MUTATION_CASES,
    assert_owner_transfer_invalidates_precomputed_admin_scope,
    assert_revoked_admin_mutation_is_rejected,
)
from tests._infra.bootstrap_exposure_rotation import assert_exposed_secret_rotation
from tests._infra.bootstrap_owner_mutation_concurrency import (
    REVOKED_OWNER_MUTATION_CASES,
    assert_revoked_pre_authenticated_owner_mutation_is_rejected,
)
from tests._infra.bootstrap_recovery import (
    _VECTOR_ADMIN_TOKEN,
    _VECTOR_PAIRING_CODE,
    _VECTOR_SECRET,
    _enable_http_bootstrap,
    _post_bootstrap,
)
from tests._infra.bootstrap_recovery_concurrency import (
    assert_concurrent_bootstrap_recovery_lock_order,
    assert_distinct_bootstrap_secrets_create_one_identity,
)
from tests._infra.bootstrap_recovery_credential_concurrency import (
    assert_cleanup_preserves_concurrent_device_recovery,
    assert_ordinary_revocations_serialize_credential_mints,
    assert_pre_authenticated_credential_mints_fail_after_rotation,
)
from tests._infra.ledger_switch_concurrency import (
    assert_switch_revalidates_locked_target_before_default_change,
)
from tests.pairing_test_support import pairing_payload

if TYPE_CHECKING:
    from tests._infra.identity import TestIdentity


@pytest.mark.real_db
def test_two_sessions_bootstrap_recovery_avoids_device_token_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_concurrent_bootstrap_recovery_lock_order(monkeypatch)
    assert_pre_authenticated_credential_mints_fail_after_rotation(monkeypatch)


@pytest.mark.real_db
def test_two_sessions_ordinary_revocations_serialize_credential_mints(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    assert_ordinary_revocations_serialize_credential_mints(
        monkeypatch,
        token_value=identity.app_token,
        device_token_value=identity.tenant_app_token,
    )


@pytest.mark.real_db
def test_two_sessions_cleanup_waits_for_device_recovery(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    assert_cleanup_preserves_concurrent_device_recovery(
        monkeypatch,
        token_value=identity.app_token,
    )


@pytest.mark.real_db
def test_two_sessions_switch_revalidates_target_before_default_change(
    monkeypatch: pytest.MonkeyPatch,
    identity: TestIdentity,
) -> None:
    assert_switch_revalidates_locked_target_before_default_change(
        monkeypatch,
        token_value=identity.app_token,
    )


@pytest.mark.real_db
@pytest.mark.parametrize("mutation", REVOKED_OWNER_MUTATION_CASES)
def test_revoked_pre_authenticated_owner_token_cannot_commit_mutation(
    identity: TestIdentity,
    mutation: str,
) -> None:
    assert_revoked_pre_authenticated_owner_mutation_is_rejected(identity, mutation)


@pytest.mark.real_db
@pytest.mark.parametrize("mutation", STALE_ADMIN_MUTATION_CASES)
def test_revoked_pre_authenticated_admin_token_cannot_mutate_device_or_upload_link(
    identity: TestIdentity,
    mutation: str,
) -> None:
    assert_revoked_admin_mutation_is_rejected(identity, mutation)


@pytest.mark.real_db
def test_owner_transfer_invalidates_precomputed_admin_upload_scope(
    identity: TestIdentity,
) -> None:
    assert_owner_transfer_invalidates_precomputed_admin_scope(identity)


@pytest.mark.real_db
def test_bootstrap_owner_rotates_credentials_after_listener_exposure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert_exposed_secret_rotation(monkeypatch)


@pytest.mark.real_db
def test_two_sessions_distinct_bootstrap_secrets_create_one_identity() -> None:
    assert_distinct_bootstrap_secrets_create_one_identity()


@pytest.mark.real_db
def test_exposed_bootstrap_principal_blocks_sensitive_identity_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()
    try:
        with TestClient(app) as client:
            bootstrapped = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert bootstrapped.status_code == 200, bootstrapped.text
            paired = client.post(
                "/api/auth/pair",
                json=pairing_payload(
                    _VECTOR_PAIRING_CODE,
                    device_name="Guarded Device",
                ),
            )
            assert paired.status_code == 200, paired.text
            with SessionLocal() as db:
                lock_bootstrap_owner_transaction(db)
                admin = db.query(AuthToken).filter(
                    AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN)
                ).one()
                with pytest.raises(AppError) as guarded:
                    assert_bootstrap_sensitive_mutation_allowed(
                        db,
                        actor_account_id=admin.account_id,
                        ledger_ids={admin.ledger_id},
                        target_device_id=admin.device_id,
                    )
                assert guarded.value.error == "bootstrap_recovery_required"
                db.rollback()

            invitation = client.post(
                "/api/ledgers/owner/invitations",
                headers={
                    "Authorization": f"Bearer {paired.json()['session_token']}"
                },
                json={"role": "member", "ttl_days": 7},
            )
            assert invitation.status_code == 409, invitation.text
            assert invitation.json()["error"] == "bootstrap_recovery_required"
    finally:
        get_settings.cache_clear()


@pytest.mark.real_db
def test_replacement_pairing_collision_is_reported_before_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement_secret = "replacement-collision-secret-with-at-least-32-bytes"
    replacement_hash = hash_pairing_code(
        derive_bootstrap_pairing_code(replacement_secret),
    )
    _enable_http_bootstrap(monkeypatch, _VECTOR_SECRET)
    Base.metadata.drop_all(bind=engine)
    init_db()
    try:
        with TestClient(app) as client:
            bootstrapped = _post_bootstrap(client, secret=_VECTOR_SECRET)
            assert bootstrapped.status_code == 200, bootstrapped.text
        with SessionLocal() as db:
            exposed_pairing = db.query(PairingCode).filter(
                PairingCode.code_hash == hash_pairing_code(_VECTOR_PAIRING_CODE)
            ).one()
            historical_at = now_utc() - timedelta(days=1)
            db.add(
                PairingCode(
                    code_hash=replacement_hash,
                    ledger_id=exposed_pairing.ledger_id,
                    account_id=exposed_pairing.account_id,
                    expires_at=historical_at,
                    used_at=historical_at,
                )
            )
            db.commit()

            with pytest.raises(ReplacementCredentialCollisionError):
                rotate_exposed_bootstrap_credentials(
                    db,
                    exposed_secret=_VECTOR_SECRET,
                    replacement_secret=replacement_secret,
                )
            db.rollback()
            assert db.query(AuthToken).filter(
                AuthToken.token_hash == hash_secret(_VECTOR_ADMIN_TOKEN)
            ).one()
            assert db.query(PairingCode).filter(
                PairingCode.code_hash == replacement_hash
            ).one()
    finally:
        get_settings.cache_clear()
