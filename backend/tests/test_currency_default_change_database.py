"""Real PostgreSQL: default changes preserve facts and serialize original commands."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.currency_binding_contract import CURRENCY_EVIDENCE_TABLES
from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import (
    AuthToken,
    Expense,
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
    InstallationIdempotencyKey,
)
from app.services.currency_adoption_service import adopt_currency_binding_for_installation_owner, adoption_preview
from app.services.currency_binding_service import resolve_write_capability
from app.services.currency_default_service import change_currency_binding_for_installation_owner
from app.services.identity_service import authenticate_desktop_session_token, bootstrap_installation_owner
from app.services.time_service import now_utc
from tests.desktop_activation_support import activate, pair_desktop

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


@pytest.fixture()
def default_owner():
    with SessionLocal() as db:
        bootstrap = bootstrap_installation_owner(db, operation_id="default-change-test", installation_id="test-installation",
            bootstrap_secret="default-change-test-secret-32-bytes", account_name="Owner", ledger_name="Ledger",
            device_name="Backend")
        db.commit()
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51201)) as client:
        payload, _ = pair_desktop(client, bootstrap.pairing_code)
        response = activate(client, payload)
        assert response.status_code == 200, response.text
        token = response.json()["session_token"]
        with SessionLocal() as db:
            auth = authenticate_desktop_session_token(db, token)
            preview = adoption_preview(db)
            adoption_key = uuid4()
            original = adopt_currency_binding_for_installation_owner(db, auth=auth, idempotency_key=adoption_key,
                expected_contract_version=preview.currency_contract_version, home_code="CNY", expected_state=preview.state,
                expected_revision=preview.binding_revision, expected_evidence_sha256=preview.evidence_sha256, reason="Initial choice")
        yield token, adoption_key, original


def change(token, *, key=None, home="JPY", revision=1):
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, token)
        return change_currency_binding_for_installation_owner(db, auth=auth, idempotency_key=key or uuid4(),
            expected_contract_version=1, home_code=home, expected_revision=revision, reason="Change default")


def financial_rows(db):
    return {table: sorted(db.scalars(text(f'SELECT to_jsonb(fact_row)::text FROM "{table}" AS fact_row')))
        for table in CURRENCY_EVIDENCE_TABLES}


def test_change_and_replay_preserve_all_financial_rows_and_the_original_adoption_receipt(default_owner):
    token, adoption_key, original_adoption = default_owner
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, token)
        resolve_write_capability(db)
        db.add(Expense(tenant_id=auth.ledger_id, amount_cents=1234, home_currency_code="CNY",
            original_currency_code="CNY", original_amount_minor=1234, status="pending", category="其他", source="test"))
        db.commit()
        before = financial_rows(db)
        activated_at = db.get(InstallationCurrencyBinding, 1).activated_at
    key = uuid4()
    original = change(token, key=key)
    change(token, home="EUR", revision=2)
    assert change(token, key=key) == original
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, token)
        assert adopt_currency_binding_for_installation_owner(db, auth=auth, idempotency_key=adoption_key,
            expected_contract_version=1, home_code="CNY", expected_state="EMPTY", expected_revision=0,
            expected_evidence_sha256=original_adoption.evidence_sha256, reason="Initial choice") == original_adoption
    with SessionLocal() as db:
        assert financial_rows(db) == before
        binding = db.get(InstallationCurrencyBinding, 1)
        assert (binding.home_currency_code, binding.binding_revision, binding.activated_at) == ("EUR", 3, activated_at)
        assert db.get(InstallationIdempotencyKey, str(adoption_key)).receipt == asdict(original_adoption)
        assert db.get(InstallationIdempotencyKey, str(key)).receipt == asdict(original)
        assert len(db.scalars(select(InstallationCurrencyAuditLog).where(
            InstallationCurrencyAuditLog.action == "OWNER_DEFAULT_CHANGE")).all()) == 2


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_change_has_one_accepted_transition(default_owner, same_key):
    token = default_owner[0]
    barrier = Barrier(2)
    keys = [uuid4(), uuid4()]
    if same_key:
        keys[1] = keys[0]

    def send(key):
        barrier.wait(timeout=5)
        try:
            return change(token, key=key)
        except AppError as error:
            return error.error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, keys))
    accepted = [result for result in results if not isinstance(result, str)]
    assert len(accepted) == (2 if same_key else 1)
    assert all(result == accepted[0] for result in accepted)
    if not same_key:
        assert "currency_binding_state_conflict" in results
    with SessionLocal() as db:
        assert db.get(InstallationCurrencyBinding, 1).binding_revision == 2
        assert len(db.scalars(select(InstallationCurrencyAuditLog).where(
            InstallationCurrencyAuditLog.action == "OWNER_DEFAULT_CHANGE")).all()) == 1


def test_old_writer_revision_is_refused_but_current_writer_can_keep_a_recorded_currency(default_owner):
    from app.runtime_compatibility_contract import (
        CURRENT_API_VERSION,
        RUNTIME_COMPATIBILITY_SESSION_KEY,
        RuntimeCompatibilityRequest,
    )

    token = default_owner[0]
    change(token)
    with SessionLocal() as db:
        db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = RuntimeCompatibilityRequest(
            api_version=CURRENT_API_VERSION, currency_binding="1:1:CNY")
        with pytest.raises(AppError) as error:
            resolve_write_capability(db)
        assert error.value.error == "currency_binding_revision_conflict"
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, token)
        resolve_write_capability(db)
        row = Expense(tenant_id=auth.ledger_id, amount_cents=200, home_currency_code="CNY",
            original_currency_code="CNY", original_amount_minor=200, status="pending", category="其他", source="test")
        db.add(row)
        db.commit()
        assert row.home_currency_code == "CNY"


def test_revoked_credential_cannot_replay_an_already_accepted_change(default_owner):
    token = default_owner[0]
    key = uuid4()
    original = change(token, key=key)
    with SessionLocal() as db:
        auth = authenticate_desktop_session_token(db, token)
        db.get(AuthToken, auth.credential_id).revoked_at = now_utc()
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AppError) as error:
            change_currency_binding_for_installation_owner(db, auth=auth, idempotency_key=key,
                expected_contract_version=1, home_code="JPY", expected_revision=1, reason="Change default")
        assert (error.value.error, error.value.status_code) == ("invalid_token", 401)
        assert db.get(InstallationIdempotencyKey, str(key)).receipt == asdict(original)
