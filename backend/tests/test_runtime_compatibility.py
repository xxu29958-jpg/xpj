"""Stable runtime compatibility negotiation across client and server writers."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.runtime_compatibility_service as runtime_compatibility_service
from app.database import SessionLocal
from app.errors import AppError
from app.models import Budget, Expense
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
from tests._infra.assets import PNG_BYTES
from tests._infra.currency import activate_test_currency_authority

pytestmark = pytest.mark.currency_binding_unbound

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def activate_currency() -> Callable[[str], None]:
    def activate(currency_code: str) -> None:
        with SessionLocal() as db:
            activate_test_currency_authority(db, currency_code)
            db.commit()
    return activate


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
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"home_currency_code": "CNY", "expected_row_version": None, "total_amount_cents": amount},
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
        headers=identity.auth_headers,
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
        "read_compatibility": "owner_action_required",
        "write_compatibility": "owner_action_required",
        "legacy_write_compatibility": "client_upgrade_required",
        "capabilities": {
            "upload_original_receipt_version": 1,
            "currency": {
                "home_currency_code": None,
                "minor_unit_exponent": None,
                "rounding_mode": None,
                "contract_version": 1,
                "binding_revision": 0,
                "request_binding": None,
                "request_binding_header": TICKETBOX_CURRENCY_BINDING_HEADER,
                "initialization_offer": None,
                "read_compatibility": "owner_action_required",
                "write_compatibility": "owner_action_required",
            }
        },
    }
    serialized = response.text.lower()
    assert "c07" not in serialized
    assert "alembic" not in serialized
    # InstallationIdempotencyKey fields stay private at every public level.
    # A product capability name containing "receipt" is not that maintenance data.
    private_fields = {"receipt", "request_fingerprint"}
    assert private_fields.isdisjoint(payload)
    assert private_fields.isdisjoint(payload["capabilities"])
    assert private_fields.isdisjoint(payload["capabilities"]["currency"])


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
            "owner_action_required",
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
        _BACKEND_ROOT / "app" / "services" / "recycle_bin_service.py",
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
    activate_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    activate_currency("JPY")

    response = client.get(
        "/api/system/runtime-compatibility",
        headers=identity.auth_headers,
    )
    assert response.status_code == 200, response.json()
    payload = response.json()
    currency = payload["capabilities"]["currency"]
    assert currency["home_currency_code"] == "JPY"
    assert currency["minor_unit_exponent"] == 0
    assert currency["rounding_mode"] == "ROUND_HALF_UP"
    assert currency["request_binding"] == "1:1:JPY"
    assert currency["initialization_offer"] is None
    assert payload["write_compatibility"] == "compatible"
    assert payload["legacy_write_compatibility"] == "client_upgrade_required"

    legacy_debts = client.get("/api/debts", headers=identity.auth_headers)
    assert legacy_debts.status_code == 200, legacy_debts.json()
    assert legacy_debts.json()["home_currency_code"] == "JPY"


def test_negotiated_jpy_writes_and_internal_jobs_consume_confirmed_binding(
    client: TestClient,
    activate_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    activate_currency("JPY")

    created = _put_budget(
        client,
        headers=_runtime_headers(identity.auth_headers, binding="1:1:JPY"),
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
        assert db.query(InstallationCurrencyAuditLog).count() == 0

        # No HTTP request marker means a trusted server-side job. It consumes
        # the persisted installation authority instead of impersonating an old
        # CNY-only client.
        internal = resolve_write_capability(db)
        assert internal.home_currency_code == "JPY"

    second = _put_budget(
        client,
        headers=_runtime_headers(identity.auth_headers, binding="1:1:JPY"),
        month="2026-09",
        amount=3400,
    )
    assert second.status_code == 200, second.json()


def test_preselection_revision_never_authorizes_a_confirmed_binding(activate_currency) -> None:
    activate_currency("JPY")
    with SessionLocal() as db:
        db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = RuntimeCompatibilityRequest(
            api_version=CURRENT_API_VERSION, currency_binding="1:0:JPY",
        )
        with pytest.raises(AppError) as stale:
            resolve_write_capability(db)
        assert stale.value.error == "currency_binding_revision_conflict"
        db.rollback()
        db.info[RUNTIME_COMPATIBILITY_SESSION_KEY] = RuntimeCompatibilityRequest(
            api_version=CURRENT_API_VERSION, currency_binding="1:1:JPY",
        )
        assert resolve_write_capability(db).binding_revision == 1


@pytest.mark.parametrize("currency", ["CNY", "JPY"])
def test_legacy_writer_is_rejected_before_any_financial_side_effect(
    currency: str,
    client: TestClient,
    activate_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    activate_currency(currency)

    response = _put_budget(client, headers=identity.auth_headers)

    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "client_upgrade_required"
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "ACTIVE"
        assert db.query(Budget).count() == 0
        assert db.query(InstallationCurrencyAuditLog).count() == 0


@pytest.mark.parametrize(
    "extra_headers",
    [
        {TICKETBOX_API_VERSION_HEADER: CURRENT_API_VERSION},
        {TICKETBOX_CURRENCY_BINDING_HEADER: "1:0:JPY"},
        {
            TICKETBOX_API_VERSION_HEADER: "2026-07-01",
            TICKETBOX_CURRENCY_BINDING_HEADER: "1:0:JPY",
        },
        {
            TICKETBOX_API_VERSION_HEADER: CURRENT_API_VERSION,
            TICKETBOX_CURRENCY_BINDING_HEADER: "01:0:JPY",
        },
    ],
)
def test_partial_stale_or_malformed_negotiation_fails_closed(
    client: TestClient,
    activate_currency: Callable[[str], None],
    extra_headers: dict[str, str],
    *,
    identity,
) -> None:
    activate_currency("JPY")

    response = _put_budget(
        client,
        headers={**identity.auth_headers, **extra_headers},
    )

    assert response.status_code == 409, response.json()
    assert response.json()["error"] == "client_upgrade_required"
    with SessionLocal() as db:
        binding = db.get(InstallationCurrencyBinding, 1)
        assert binding is not None
        assert binding.state == "ACTIVE"
        assert db.query(Budget).count() == 0


def test_stale_binding_is_refused_while_environment_cannot_change_confirmed_currency(
    client: TestClient, web_client: TestClient, activate_currency, monkeypatch, *, identity,
) -> None:
    activate_currency("CNY")
    initial = _put_budget(client, headers=identity.app_headers)
    assert initial.status_code == 200, initial.json()
    stale = _put_budget(client, headers=_runtime_headers(identity.auth_headers, binding="1:0:CNY"), month="2026-09")
    assert stale.status_code == 409
    assert stale.json()["error"] == "currency_binding_revision_conflict"
    monkeypatch.setenv("FX_HOME_CURRENCY_CODE", "JPY")
    snapshot = client.get("/api/system/runtime-compatibility", headers=identity.auth_headers).json()
    assert snapshot["write_compatibility"] == "compatible"
    assert snapshot["capabilities"]["currency"]["request_binding"] == "1:1:CNY"
    page = web_client.get("/web/budgets?ledger_id=owner&month=2026-08")
    assert page.status_code == 200
    assert 'name="total_amount_yuan" value="12.00"' in page.text
    current = _put_budget(client, headers=_runtime_headers(identity.auth_headers, binding="1:1:CNY"), month="2026-10")
    assert current.status_code == 200, current.json()
    with SessionLocal() as db:
        assert db.get(InstallationCurrencyBinding, 1).home_currency_code == "CNY"


def test_empty_installation_cannot_be_activated_by_a_fabricated_money_binding(client: TestClient, *, identity) -> None:
    snapshot = client.get("/api/system/runtime-compatibility", headers=identity.auth_headers).json()
    assert snapshot["capabilities"]["currency"]["request_binding"] is None
    refused = _put_budget(client, headers=_runtime_headers(identity.auth_headers, binding="1:0:JPY"))
    assert refused.status_code == 409
    assert refused.json()["error"] == "currency_adoption_required"
    with SessionLocal() as db:
        assert db.get(InstallationCurrencyBinding, 1).state == "EMPTY"
        assert db.query(Budget).count() == 0
        assert db.query(InstallationCurrencyAuditLog).count() == 0


def test_upload_link_uses_confirmed_non_cny_binding(
    client: TestClient,
    activate_currency: Callable[[str], None],
    *,
    identity,
) -> None:
    activate_currency("JPY")

    uploaded = client.post(
        identity.upload_url_path,
        headers={**identity.upload_headers, "Content-Type": "image/png"},
        content=PNG_BYTES,
    )

    assert uploaded.status_code == 200, uploaded.json()
    with SessionLocal() as db:
        authority = db.get(InstallationCurrencyBinding, 1)
        expense = db.get(Expense, uploaded.json()["id"])
        assert authority is not None
        assert authority.state == "ACTIVE"
        assert authority.home_currency_code == "JPY"
        assert expense is not None
        assert expense.home_currency_code == "JPY"


def test_openapi_publishes_runtime_headers_on_mutating_api_operations(
    client: TestClient,
) -> None:
    schema = client.app.openapi()
    expected_names = {"Ticketbox-Api-Version", "Ticketbox-Currency-Binding"}
    for path, method in (
        ("/api/budgets/monthly/{month}", "put"),
        ("/api/goals", "post"),
        ("/api/expenses/manual", "post"),
    ):
        parameters = schema["paths"][path][method]["parameters"]
        resolved = [
            schema["components"]["parameters"][parameter["$ref"].rsplit("/", 1)[-1]]
            if "$ref" in parameter else parameter
            for parameter in parameters
        ]
        assert expected_names <= {parameter.get("name") for parameter in resolved if parameter.get("in") == "header"}
        for name in expected_names:
            assert sum(parameter.get("name") == name for parameter in resolved) == 1

    currency_parameter = schema["components"]["parameters"][
        "TicketboxCurrencyBinding"
    ]
    assert currency_parameter["required"] is False
    assert currency_parameter["schema"]["pattern"].endswith(":[A-Z]{3}$")
