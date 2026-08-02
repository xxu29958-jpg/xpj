"""Explicit persisted-currency setup for product tests.

This helper is deliberately test-only.  It models an already completed owner
adoption so read/presentation tests can seed JPY/KRW facts without reviving the
retired ``FX_HOME_CURRENCY_CODE``-as-authority bridge.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.currency_adoption_evidence import currency_adoption_evidence_sha256
from app.currency_binding_contract import CURRENCY_ROUNDING_MODE
from app.fx_constants import CURRENCY_MINOR_UNIT_DIGITS
from app.models import InstallationCurrencyBinding
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc


def activate_test_currency_authority(db: Session, currency_code: str) -> None:
    """Activate or re-authorize one synthetic persisted installation binding."""

    binding = db.get(InstallationCurrencyBinding, 1)
    assert binding is not None
    if binding.state == "ACTIVE":
        assert binding.home_currency_code == currency_code
        resolve_write_capability(db, expected_revision=binding.binding_revision)
        return
    assert binding.state == "EMPTY"
    activated_at = now_utc()
    binding.state = "ACTIVE"
    binding.home_currency_code = currency_code
    binding.minor_unit_exponent = CURRENCY_MINOR_UNIT_DIGITS[currency_code]
    binding.rounding_mode = CURRENCY_ROUNDING_MODE
    binding.binding_revision = 1
    binding.provenance = "OWNER_ADOPTION"
    binding.evidence_sha256 = currency_adoption_evidence_sha256(db.connection())
    binding.updated_at = activated_at
    binding.activated_at = activated_at
    db.flush()
    resolve_write_capability(db, expected_revision=1)
