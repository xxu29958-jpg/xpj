"""Stable runtime compatibility negotiation across client and server writers."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.runtime_compatibility_service as runtime_compatibility_service
from app.config import get_settings
from app.database import SessionLocal
from app.errors import AppError
from app.models import Budget
from app.models.currency_binding import (
    InstallationCurrencyAuditLog,
    InstallationCurrencyBinding,
)
from app.runtime_compatibility_contract import (
    CURRENT_API_VERSION,
    RUNTIME_COMPATIBILITY_CONTRACT,
    RUNTIME_COMPATIBILITY_SESSION_KEY,
    TICKETBOX_API_VERSION_HEADER,
    TICKETBOX_CURRENCY_BINDING_HEADER,
    RuntimeCompatibilityRequest,
)
from app.services.currency_binding_service import (
    CurrencyCapability,
    resolve_write_capability,
)

pytestmark = pytest.mark.currency_binding_unbound

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def configure_home_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str], None]:
    original = os.environ.get("FX_HOME_CURRENCY_CODE")

    def configure(currency_code: str) -> None:
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", currency_code)
        get_settings.cache_clear()

    yield configure
    if original is None:
        monkeypatch.delenv("FX_HOME_CURRENCY_CODE", raising=False)
    else:
        monkeypatch.setenv("FX_HOME_CURRENCY_CODE", original)
    get_settings.cache_clear()


def _runtime_headers(
    app_headers: dict[str, str],
    *,
    binding: str,
    api_version: str = CURRENT_API_VERSION,
) -> dict[str, str]:
    return {
        **app_headers,
        TICKETBOX_API_VERSION_HEADER: api_version,
        TICKETBOX_CURRENCY_BINDING_HEADER: binding,
    }


def _put_budget(
    client: TestClient,
    *,
    headers: dict[str, str],
    month: str = "2026-08",
    amount: int = 1200,
):
    return client.put(
        f"/api/budgets/monthly/{month}",
        headers=headers,
        json={"total_amount_cents": amount},
    )


def test_runtime_snapshot_is_authenticated_private_and_product_facing(
    client: TestClient,
    *,
    identity,
) -> None:
    anonymous = client.get("/api/system/runtime-compatibility")
    assert anonymous.status_code == 401

    response = client.get(
        "/api/system/runtime-compatibility",
        headers=identity.app_headers,
    )

    assert response.status_code == 200, response.json()
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"
    payload = response.json()
    observed_at = payload.pop("observed_at")
    assert observed_at.endswith("Z")
    assert payload == {
        "contract": RUNTIME_COMPATIBILITY_CONTRACT,
        "api_version": CURRENT_API_VERSION,
        "api_version_header": TICKETBOX_API_VERSION_HEADER,
        "read_compatibility": "compatible",
        "write_compatibility": "compatible",
        "legacy_write_compatibility": "compatible",
        "capabilities": {
            "currency": {
                "home_currency_code": "CNY",
                "minor_unit_exponent": 2,
                "rounding_mode": "ROUND_HALF_UP",
                "contract_version": 1,
                "binding_revision": 0,
                "request_binding": "1:0",
                "request_binding_header": TICKETBOX_CURRENCY_BINDING_HEADER,
                "initialization_offer": "CNY",
                "read_compatibility": "compatible",
                "write_compatibility": "compatible",
            }
        },
    }
    serialized = response.text.lower()
    assert "c07" not in serialized
    assert "alembic" not in serialized
    assert "receipt" not in serialized


def test_runtime_snapshot_maps_non_ready_states_to_product_conclusions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        (
            CurrencyCapability(
                state="ADOPTION_REQUIRED",
                home_currency_code=None,
                minor_unit_exponent=None,
                rounding_mode=None,
                currency_contract_version=1,
                binding_revision=0,
                minimum_writable_currency_contract=1,
                health="adoption_required",
                initialization_offer=None,
            ),
            "owner_action_required",
        ),
        (
            CurrencyCapability(
                state="ACTIVE",
                home_currency_code="CNY",
                minor_unit_exponent=2,
                rounding_mode="ROUND_HALF_UP",
                currency_contract_version=2,
                binding_revision=1,
                minimum_writable_currency_contract=1,
                health="migration_required",
                initialization_offer=None,
            ),
            "server_upgrade_required",
        ),
        (
            CurrencyCapability(
                state="EMPTY",
                home_currency_code=None,
                minor_unit_exponent=None,
                rounding_mode=None,
                currency_contract_version=1,
                binding_revision=0,
                minimum_writable_currency_contract=1,
                health="empty",
                initialization_offer=None,
            ),
            "configuration_required",
        ),
    ]
    with SessionLocal() as db:
        for capability, expected in cases:
            monkeypatch.setattr(
                runtime_compatibility_service,
                "get_capability",
                lambda _db, value=capability: value,
            )
            snapshot = runtime_compatibility_service.runtime_compatibility_snapshot(
                db
            )
            assert snapshot.read_compatibility == expected
            assert snapshot.write_compatibility == expected
            assert snapshot.legacy_write_compatibility == "client_upgrade_required"


def test_product_presentation_paths_do_not_fall_back_to_runtime_env() -> None:
    route_files = (_BACKEND_ROOT / "app" / "routes").rglob("*.py")
    service_files = [
        _BACKEND_ROOT / "app" / "services" / "budget_advisor_service" / "_runner.py",
        _BACKEND_ROOT / "app" / "services" / "owner_console_service" / "_index.py",
        _BACKEND_ROOT
        / "app"
        / "services"
        / "owner_console_service"
        / "_recycle_bin.py",
        _BACKEND_ROOT / "app" / "services" / "reports_service" / "_api.py",
        _BACKEND_ROOT / "app" / "services" / "web_stats_service.py",
    ]
    direct_env_call = re.compile(r"\bhome_currency_code\s*\(\s*\)")
    offenders = [
        path.relative_to(_BACKEND_ROOT).as_posix()
        for path in [*route_files, *service_files]
        if direct_env_call.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_jpy_snapshot_exposes_minor_unit_without_expanding_legacy_envelope(
    client: TestClient,
    configure_home_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    configure_home_currency("JPY")

    response = client.get(
        "/api/system/runtime-compatibility",
        headers=identity.app_headers,
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    currency = payload["capabilities"]["currency"]
    assert currency["home_currency_code"] == "JPY"
    assert currency["minor_unit_exponent"] == 0
    assert currency["rounding_mode"] == "ROUND_HALF_UP"
    assert currency["request_binding"] == "1:0"
    assert currency["initialization_offer"] == "JPY"
    assert payload["write_compatibility"] == "compatible"
    assert payload["legacy_write_compatibility"] == "client_upgrade_required"

    legacy_debts = client.get("/api/debts", headers=identity.app_headers)
    assert legacy_debts.status_code == 200, legacy_debts.json()
    assert legacy_debts.json()["home_currency_code"] is None


def test_negotiated_jpy_first_write_claims_binding_and_internal_jobs_follow_it(
    client: TestClient,
    configure_home_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    configure_home_currency("JPY")

    created = _put_budget(
        client,
        headers=_runtime_headers(identity.app_headers, binding="1:0"),
    )
    assert created.status_code == 200, created.json()

    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "ACTIVE"
        assert binding.home_currency_code == "JPY"
        assert binding.minor_unit_exponent == 0
        assert binding.binding_revision == 1
        assert db.scalar(
            select(Budget.total_amount_cents).where(
                Budget.tenant_id == "owner",
                Budget.month == "2026-08",
            )
        ) == 1200
        assert db.query(InstallationCurrencyAuditLog).count() == 1

        # No HTTP request marker means a trusted server-side job. It consumes
        # the persisted installation authority instead of impersonating an old
        # CNY-only client.
        internal = resolve_write_capability(db)
        assert internal.home_currency_code == "JPY"

    second = _put_budget(
        client,
        headers=_runtime_headers(identity.app_headers, binding="1:1"),
        month="2026-09",
        amount=3400,
    )
    assert second.status_code == 200, second.json()


def test_initial_revision_is_reusable_only_inside_the_claiming_transaction(
    configure_home_currency: Callable[[str], None],
) -> None:
    configure_home_currency("JPY")
    request = RuntimeCompatibilityRequest(
        api_version=CURRENT_API_VERSION,
        currency_binding="1:0",
    )

    with SessionLocal() as db:
        db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = request
        first = resolve_write_capability(db)
        second = resolve_write_capability(db)
        assert first.binding_revision == 1
        assert second.binding_revision == 1
        db.commit()

        with pytest.raises(AppError) as stale:
            resolve_write_capability(db)
        assert stale.value.error == "currency_binding_revision_conflict"


def test_legacy_jpy_writer_is_rejected_before_any_financial_side_effect(
    client: TestClient,
    configure_home_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    configure_home_currency("JPY")

    response = _put_budget(client, headers=identity.app_headers)

    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "client_upgrade_required"
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "EMPTY"
        assert db.query(Budget).count() == 0
        assert db.query(InstallationCurrencyAuditLog).count() == 0


@pytest.mark.parametrize(
    "extra_headers",
    [
        {TICKETBOX_API_VERSION_HEADER: CURRENT_API_VERSION},
        {TICKETBOX_CURRENCY_BINDING_HEADER: "1:0"},
        {
            TICKETBOX_API_VERSION_HEADER: "2026-07-01",
            TICKETBOX_CURRENCY_BINDING_HEADER: "1:0",
        },
        {
            TICKETBOX_API_VERSION_HEADER: CURRENT_API_VERSION,
            TICKETBOX_CURRENCY_BINDING_HEADER: "01:0",
        },
    ],
)
def test_partial_stale_or_malformed_negotiation_fails_closed(
    client: TestClient,
    configure_home_currency: Callable[[str], None],
    extra_headers: dict[str, str],
    *,
    identity,
) -> None:
    configure_home_currency("JPY")

    response = _put_budget(
        client,
        headers={**identity.app_headers, **extra_headers},
    )

    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "client_upgrade_required"
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "EMPTY"
        assert db.query(Budget).count() == 0


def test_stale_binding_revision_and_configuration_drift_are_distinct(
    client: TestClient,
    web_client: TestClient,
    configure_home_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    initial = _put_budget(client, headers=identity.app_headers)
    assert initial.status_code == 200, initial.json()

    stale = _put_budget(
        client,
        headers=_runtime_headers(identity.app_headers, binding="1:0"),
        month="2026-09",
    )
    assert stale.status_code == 409, stale.json()
    assert stale.json()["error"] == "currency_binding_revision_conflict"

    configure_home_currency("JPY")
    snapshot = client.get(
        "/api/system/runtime-compatibility",
        headers=identity.app_headers,
    )
    assert snapshot.status_code == 200, snapshot.json()
    payload = snapshot.json()
    assert payload["read_compatibility"] == "compatible"
    assert payload["write_compatibility"] == "configuration_required"
    assert payload["capabilities"]["currency"]["home_currency_code"] == "CNY"
    assert payload["capabilities"]["currency"]["request_binding"] == "1:1"

    budgets_page = web_client.get(
        "/web/budgets?ledger_id=owner&month=2026-08"
    )
    assert budgets_page.status_code == 200, budgets_page.text
    assert "月度总预算（CNY" in budgets_page.text
    assert 'name="total_amount_yuan" value="12.00"' in budgets_page.text
    assert "月度总预算（JPY" not in budgets_page.text

    drifted = _put_budget(
        client,
        headers=_runtime_headers(identity.app_headers, binding="1:1"),
        month="2026-10",
    )
    assert drifted.status_code == 409, drifted.json()
    assert drifted.json()["error"] == "currency_binding_configuration_drift"
