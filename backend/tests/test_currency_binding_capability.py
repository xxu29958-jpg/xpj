from __future__ import annotations

import pytest

from app.currency_binding_contract import CURRENCY_EVIDENCE_TABLES
from app.database import SessionLocal
from app.database._currency_writer import (
    lock_currency_evidence_tables,
    set_currency_writer_proof,
)
from app.errors import AppError
from app.models import Budget
from app.models.currency_binding import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
)
from app.routes import currency_system
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
    assert "capabilities" in RuntimeCompatibilitySnapshotResponse.model_fields
    assert "expenses" in CURRENCY_EVIDENCE_TABLES
    assert callable(lock_currency_evidence_tables)
    assert callable(set_currency_writer_proof)
    assert client.get("/api/system/currency-capability").status_code == 404
    paths = client.app.openapi()["paths"]
    assert "/api/system/currency-capability" not in paths
    assert "/api/system/runtime-compatibility" in paths
    assert "/api/maintenance/currency-binding/adoption" not in paths
    assert client.get("/api/maintenance/currency-binding/adoption").status_code == 404


@pytest.mark.real_db
def test_ordinary_money_writes_cannot_choose_or_activate_currency(identity) -> None:
    _ = identity
    for _attempt in range(2):
        with SessionLocal() as db:
            with pytest.raises(AppError) as refused:
                resolve_write_capability(db)
            assert refused.value.error == "currency_adoption_required"
            db.rollback()
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding.state == "EMPTY"
        assert binding.home_currency_code is None
        assert binding.binding_revision == 0
        assert db.query(InstallationCurrencyAuditLog).count() == 0
        assert db.query(Budget).count() == 0


