"""Committed pair response loss resumes through the real backend and BFF."""

from pathlib import Path

import pytest

from backend_manager.app_controller import AppController
from backend_manager.product_data import ProductDataError, pair_product_session
from tests._real_backend import (
    E2E_INSTALLATION_ID,
    CredentialStores,
    HealthyE2ERuntime,
    RealBackend,
    e2e_manager_config,
    make_manager,
    manager_bootstrap_cookies,
    manager_get,
    serving,
)

pytest_plugins = ["tests._real_backend"]


def test_original_code_resumes_a_committed_pair_after_response_loss(tmp_path: Path, real_backend: RealBackend) -> None:
    stores = CredentialStores()
    attempts = []
    original_code = real_backend.fresh_pairing_code()

    def lossy_pairer(origin, code, *, attempt, **kwargs):
        result = pair_product_session(origin, code, attempt=attempt, **kwargs)
        attempts.append(attempt)
        if len(attempts) == 1:
            raise ProductDataError("response lost after backend commit", status_code=503)
        return result

    def controller() -> AppController:
        return AppController(HealthyE2ERuntime(), e2e_manager_config(real_backend.port),
            product_session_pairer=lossy_pairer, **stores.controller_kwargs())

    with pytest.raises(ProductDataError):
        controller().pair_product_principal(original_code)
    pending = stores.recoveries[E2E_INSTALLATION_ID]
    restarted = controller()
    assert restarted.product_principal() == {"configured": False, "pairing_recovery": "original_code_required"}
    assert len(attempts) == 1
    assert stores.recoveries[E2E_INSTALLATION_ID] == pending
    paired = restarted.pair_product_principal(original_code)
    assert paired["configured"] is True
    assert paired["ledger_id"] == real_backend.owner_ledger_id
    assert attempts[0] == attempts[1]
    assert stores.recoveries == {}
    manager = make_manager(restarted)
    with serving(manager):
        cookie = manager_bootstrap_cookies(manager, tmp_path / "resumed-bootstrap.html")
        status, body = manager_get(manager, "/web/pending", cookie)
    assert status == 200
    assert "我的小票夹" in body
