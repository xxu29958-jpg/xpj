from __future__ import annotations

import pytest

from app.config import get_settings
from app.currency_binding_contract import CURRENCY_EVIDENCE_TABLES
from app.database import SessionLocal
from app.database._currency_writer import (
    lock_currency_evidence_tables,
    set_currency_writer_proof,
)
from app.errors import AppError
from app.main import app
from app.models import Budget
from app.models.currency_binding import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
)
from app.network_boundary import require_maintenance_local
from app.routes import currency_adoption, currency_system
from app.schemas._currency import RuntimeCompatibilitySnapshotResponse
from app.services import currency_binding_service
from app.services.currency_binding_service import (
    get_capability,
    resolve_write_capability,
)

pytestmark = pytest.mark.currency_binding_unbound


def test_missing_binding_singleton_is_corruption(monkeypatch) -> None:
    monkeypatch.setattr(
        currency_binding_service,
        "_load_binding",
        lambda *_args, **_kwargs: None,
    )
    with SessionLocal() as db, pytest.raises(AppError) as exc_info:
        get_capability(db)

    assert exc_info.value.error == "currency_binding_corrupt"
    assert exc_info.value.status_code == 503


def test_runtime_compatibility_is_the_only_client_currency_capability(client) -> None:
    assert currency_system.router.prefix == "/api/system"
    assert currency_adoption.router.prefix == "/api/maintenance/currency-binding"
    assert "capabilities" in RuntimeCompatibilitySnapshotResponse.model_fields
    assert "expenses" in CURRENCY_EVIDENCE_TABLES
    assert callable(lock_currency_evidence_tables)
    assert callable(set_currency_writer_proof)
    assert client.get("/api/system/currency-capability").status_code == 404
    paths = client.app.openapi()["paths"]
    assert "/api/system/currency-capability" not in paths
    assert "/api/system/runtime-compatibility" in paths


def test_adoption_boundary_ignores_public_admin_escape_hatch(client, identity, monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    get_settings.cache_clear()
    try:
        response = client.get(
            "/api/maintenance/currency-binding/adoption",
            headers=identity.admin_headers,
        )
        assert response.status_code == 403
        assert response.json()["error"] == "maintenance_local_only"
    finally:
        get_settings.cache_clear()


def test_currency_adoption_requires_admin_auth_after_local_boundary(client) -> None:
    # coverage: auth-401
    app.dependency_overrides[require_maintenance_local] = lambda: None
    try:
        response = client.post(
            "/api/maintenance/currency-binding/adoption",
            headers={"Idempotency-Key": "b588366e-c55c-4ecc-a928-8de4a4569767"},
            json={
                "currency_contract_version": 1,
                "home_currency_code": "CNY",
                "expected_state": "ADOPTION_REQUIRED",
                "expected_binding_revision": 0,
                "expected_evidence_sha256": "0" * 64,
                "reason": "authentication boundary regression",
            },
        )
    finally:
        app.dependency_overrides.pop(require_maintenance_local, None)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


def test_local_admin_can_preview_adoption_state(client, identity) -> None:
    app.dependency_overrides[require_maintenance_local] = lambda: None
    try:
        response = client.get(
            "/api/maintenance/currency-binding/adoption",
            headers=identity.admin_headers,
        )
    finally:
        app.dependency_overrides.pop(require_maintenance_local, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "EMPTY"
    assert payload["binding_revision"] == 0
    assert len(payload["evidence_sha256"]) == 64
    assert payload["evidence_health"] == "adoptable"
    assert set(payload["allowed_home_currency_codes"]) == {
        "CNY",
        "EUR",
        "GBP",
        "HKD",
        "JPY",
        "KRW",
        "USD",
    }


@pytest.mark.real_db
def test_first_fact_claim_is_transactional_and_audited(identity) -> None:
    _ = identity
    # Session A caches EMPTY before session B wins the first-fact claim.  The
    # subsequent FOR UPDATE in A must refresh to B's committed ACTIVE row,
    # not attempt a second state transition with stale ORM attributes.
    with SessionLocal() as second_writer:
        assert get_capability(second_writer).state == "EMPTY"
        with SessionLocal() as first_writer:
            capability = resolve_write_capability(first_writer)
            assert capability.state == "ACTIVE"
            assert capability.home_currency_code == "CNY"
            first_writer.add(
                Budget(
                    tenant_id="owner",
                    month="2026-08",
                    total_amount_cents=100,
                    non_monthly_amount_cents=0,
                    rollover_amount_cents=0,
                )
            )
            first_writer.commit()

        capability = resolve_write_capability(second_writer)
        assert capability.state == "ACTIVE"
        assert capability.home_currency_code == "CNY"
        second_writer.add(
            Budget(
                tenant_id="owner",
                month="2026-09",
                total_amount_cents=200,
                non_monthly_amount_cents=0,
                rollover_amount_cents=0,
            )
        )
        second_writer.commit()

    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "ACTIVE"
        assert binding.binding_revision == 1
        assert binding.minor_unit_exponent == 2
        assert binding.rounding_mode == "ROUND_HALF_UP"
        audit = db.query(InstallationCurrencyAuditLog).one()
        assert audit.action == "FIRST_FACT_CLAIM"
        assert audit.before_snapshot["state"] == "EMPTY"
        assert audit.after_snapshot["state"] == "ACTIVE"
        assert db.query(Budget).count() == 2


def test_first_fact_claim_rolls_back_with_abandoned_write(identity) -> None:
    _ = identity
    with SessionLocal() as db:
        resolve_write_capability(db)
        db.add(
            Budget(
                tenant_id="owner",
                month="2026-08",
                total_amount_cents=100,
                non_monthly_amount_cents=0,
                rollover_amount_cents=0,
            )
        )
        db.rollback()

    with SessionLocal() as db:
        assert get_capability(db).state == "EMPTY"
        assert db.query(InstallationCurrencyAuditLog).count() == 0
