from __future__ import annotations

import pytest

from app.config import get_settings
from app.currency_binding_contract import CURRENCY_EVIDENCE_TABLES
from app.database import SessionLocal
from app.database._currency_writer import (
    lock_currency_evidence_tables,
    set_currency_writer_proof,
)
from app.main import app
from app.models import Budget
from app.models.currency_binding import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
)
from app.network_boundary import require_maintenance_local
from app.routes import currency_adoption, currency_system
from app.schemas._currency import CurrencyCapabilityResponse
from app.services.currency_binding_service import (
    get_capability,
    resolve_write_capability,
)

pytestmark = pytest.mark.currency_binding_unbound


def test_currency_capability_requires_session_and_is_private(client, identity) -> None:
    assert currency_system.router.prefix == "/api/system"
    assert currency_adoption.router.prefix == "/api/maintenance/currency-binding"
    assert "binding_revision" in CurrencyCapabilityResponse.model_fields
    assert "expenses" in CURRENCY_EVIDENCE_TABLES
    assert callable(lock_currency_evidence_tables)
    assert callable(set_currency_writer_proof)
    anonymous = client.get("/api/system/currency-capability")
    assert anonymous.status_code == 401

    response = client.get(
        "/api/system/currency-capability",
        headers=identity.app_headers,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"
    assert response.json() == {
        "state": "EMPTY",
        "home_currency_code": None,
        "minor_unit_exponent": None,
        "rounding_mode": None,
        "currency_contract_version": 1,
        "binding_revision": 0,
        "minimum_writable_currency_contract": 1,
        "health": "empty",
        "initialization_offer": "CNY",
    }


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


def test_first_fact_claim_is_transactional_and_audited(identity) -> None:
    _ = identity
    with SessionLocal() as db:
        capability = resolve_write_capability(db)
        assert capability.state == "ACTIVE"
        assert capability.home_currency_code == "CNY"
        db.add(
            Budget(
                tenant_id="owner",
                month="2026-08",
                total_amount_cents=100,
                non_monthly_amount_cents=0,
                rollover_amount_cents=0,
            )
        )
        db.commit()

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
