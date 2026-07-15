"""Cross-ledger isolation tests for v0.4-alpha1.

These tests target the selected-ledger boundary. An Account/Device session is
stable across ``POST /api/ledgers/{id}/switch``; every request still resolves
one ledger and revalidates active Membership before touching financial data.
Query-string forgery never selects a ledger, and a request header is context,
not authority.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from api_contract_helpers import (
    confirm_expense_api,
    patch_expense,
    reject_expense_api,
    upload_png,
)
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _pairing as owner_pairing_route
from app.routes.owner_console import _require_local as _owner_console_require_local
from app.routes.owner_ledgers import _require_local as _owner_ledgers_require_local
from tests._infra.assets import PNG_BYTES
from tests.pairing_test_support import pairing_payload


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """TestClient with Owner Console loopback dependency bypassed."""
    app.dependency_overrides[_owner_console_require_local] = lambda: None
    app.dependency_overrides[_owner_ledgers_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_owner_console_require_local, None)
    app.dependency_overrides.pop(_owner_ledgers_require_local, None)


def _create_ledger(client: TestClient, name: str, *, identity) -> str:
    response = client.post(
        "/api/ledgers", headers=identity.admin_headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()["ledger_id"]


def _switch(client: TestClient, headers: dict[str, str], ledger_id: str) -> str:
    response = client.post(
        f"/api/ledgers/{ledger_id}/switch", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["session_token"]


def test_switched_session_only_sees_selected_ledger_pending(
    client: TestClient,
    *,
    identity,
) -> None:
    # Seed ledger "owner" with a confirmed-track expense via owner upload key.
    owner_pending_id = upload_png(client, identity=identity)
    assert owner_pending_id > 0

    new_ledger = _create_ledger(client, "家庭账本", identity=identity)

    # Select the new (empty) ledger without replacing the session secret.
    session_token = _switch(client, identity.app_headers, new_ledger)
    original_token = identity.app_headers["Authorization"].removeprefix("Bearer ")
    assert session_token == original_token

    # Pending list reflects ONLY the new ledger.
    pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert pending.status_code == 200
    assert pending.json() == []

    # The same session can select the owner ledger because the Account has an
    # active Membership there. This does not mutate or replace the session.
    owner_headers = {
        **identity.app_headers,
        "X-Ticketbox-Ledger-ID": "owner",
    }
    pending_again = client.get("/api/expenses/pending", headers=owner_headers)
    assert pending_again.status_code == 200
    assert any(item["id"] == owner_pending_id for item in pending_again.json())


def test_switch_keeps_one_session_valid_across_authorized_ledgers(
    client: TestClient,
    *,
    identity,
) -> None:
    new_ledger = _create_ledger(client, "家庭账本", identity=identity)
    token = _switch(client, identity.app_headers, new_ledger)
    assert token == identity.app_headers["Authorization"].removeprefix("Bearer ")

    target = client.get("/api/auth/check", headers=identity.app_headers)
    assert target.status_code == 200
    assert target.json()["ledger_id"] == new_ledger

    owner = client.get(
        "/api/auth/check",
        headers={
            **identity.app_headers,
            "X-Ticketbox-Ledger-ID": "owner",
        },
    )
    assert owner.status_code == 200
    assert owner.json()["ledger_id"] == "owner"


def test_forged_ledger_id_query_does_not_cross(client: TestClient, *, identity) -> None:
    # Upload to "tester_1" ledger via the gray app token.
    tester_response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.gray_app_headers,
        files={"file": ("gray.png", PNG_BYTES, "image/png")},
    )
    assert tester_response.status_code == 200
    tester_id = int(tester_response.json()["id"])

    # The owner-bound app token must NOT be able to read the tester ledger
    # by adding a ledger_id query parameter — the server only honours
    # AuthContext.ledger_id derived from the token.
    owner_view = client.get(
        "/api/expenses/pending?ledger_id=tester_1",
        headers=identity.app_headers,
    )
    assert owner_view.status_code == 200
    assert all(item["id"] != tester_id for item in owner_view.json())

    # Image route also rejects cross-ledger reads regardless of query string.
    image = client.get(
        f"/api/expenses/{tester_id}/image?ledger_id=tester_1",
        headers=identity.app_headers,
    )
    assert image.status_code == 404


def test_selected_ledger_write_revalidates_membership_inside_commit_lock(
    client: TestClient,
    *,
    identity,
) -> None:
    selected_headers = {
        **identity.app_headers,
        "X-Ticketbox-Ledger-ID": "tester_1",
    }

    uploaded = client.post(
        "/api/app/upload-screenshot",
        headers=selected_headers,
        files={"file": ("selected-ledger.png", PNG_BYTES, "image/png")},
    )

    assert uploaded.status_code == 200, uploaded.text
    public_id = uploaded.json()["public_id"]
    selected_rows = client.get(
        "/api/expenses/pending",
        headers=selected_headers,
    ).json()
    owner_rows = client.get(
        "/api/expenses/pending",
        headers=identity.app_headers,
    ).json()
    assert any(row["public_id"] == public_id for row in selected_rows)
    assert all(row["public_id"] != public_id for row in owner_rows)


def test_upload_link_uploads_only_into_its_ledger(client: TestClient, *, identity) -> None:
    # Tester upload link is bound to "tester_1"; uploads must land there
    # even when an unrelated app token would otherwise be in scope.
    response = client.post(
        identity.gray_upload_url_path,
        headers=identity.gray_upload_headers,
        files={"file": ("via-upload-link.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    public_id = response.json()["public_id"]

    # Owner-bound app token cannot see this expense in any list / search.
    owner_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert owner_pending.status_code == 200
    assert all(row["public_id"] != public_id for row in owner_pending.json())

    # Tester app token sees it.
    tester_pending = client.get("/api/expenses/pending", headers=identity.gray_app_headers)
    assert tester_pending.status_code == 200
    assert any(row["public_id"] == public_id for row in tester_pending.json())


def test_pairing_to_new_ledger_yields_isolated_token(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity,
) -> None:
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url="https://finance.example.test",
        ),
    )
    new_ledger = _create_ledger(local_client, "家庭账本", identity=identity)

    # Generate a pairing code targeting the new ledger via Owner Console flow.
    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": new_ledger, "ttl_minutes": "10"},
    )
    assert response.status_code == 200
    import re

    match = re.search(
        r'class="code-big"[^>]*>\s*(\d{8})\s*<', response.text
    )
    assert match, "expected an 8-digit pairing code rendered in .code-big"
    pairing_code = match.group(1)

    # Pair as a new device.
    pair = local_client.post(
        "/api/auth/pair",
        json=pairing_payload(
            pairing_code,
            device_name="pytest-family-android",
        ),
    )
    assert pair.status_code == 200, pair.text
    new_token = pair.json()["session_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    # The new token's ledger must be the new one, not the default.
    check = local_client.get("/api/auth/check", headers=new_headers)
    assert check.status_code == 200
    assert check.json()["ledger_name"] == "家庭账本"

    # Default-ledger pending entries (created by the conftest owner) are
    # invisible to this token.
    owner_pending_id = upload_png(local_client, identity=identity)  # writes to "owner" ledger
    family_pending = local_client.get("/api/expenses/pending", headers=new_headers)
    assert family_pending.status_code == 200
    assert all(row["id"] != owner_pending_id for row in family_pending.json())


# ---------------------------------------------------------------------------
# Cross-token CRUD tests: token A must never write/read token B's expenses.
# These tests don't switch ledgers — both tokens stay valid in parallel — so
# they pin down the route-level guard that rejects cross-tenant writes even
# when both sessions are alive.
# ---------------------------------------------------------------------------


def _gray_pending_id(client: TestClient, *, identity) -> int:
    response = client.post(
        "/api/app/upload-screenshot",
        headers=identity.gray_app_headers,
        files={"file": ("gray.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["id"])


def test_owner_cannot_patch_tester_expense(client: TestClient, *, identity) -> None:
    tester_id = _gray_pending_id(client, identity=identity)
    response = patch_expense(
        client,
        tester_id,
        headers=identity.app_headers,
        fields={"merchant": "owner-tries-to-overwrite"},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "expense_not_found"


def test_owner_cannot_confirm_tester_expense(client: TestClient, *, identity) -> None:
    tester_id = _gray_pending_id(client, identity=identity)
    response = confirm_expense_api(client, tester_id, headers=identity.app_headers)
    assert response.status_code == 404


def test_owner_cannot_reject_tester_expense(client: TestClient, *, identity) -> None:
    tester_id = _gray_pending_id(client, identity=identity)
    response = reject_expense_api(client, tester_id, headers=identity.app_headers)
    assert response.status_code == 404


def test_owner_cannot_read_tester_expense_detail(client: TestClient, *, identity) -> None:
    tester_id = _gray_pending_id(client, identity=identity)
    detail = client.get(f"/api/expenses/{tester_id}", headers=identity.app_headers)
    assert detail.status_code == 404
    image = client.get(f"/api/expenses/{tester_id}/image", headers=identity.app_headers)
    assert image.status_code == 404
    thumb = client.get(f"/api/expenses/{tester_id}/thumbnail", headers=identity.app_headers)
    assert thumb.status_code == 404


def test_csv_export_is_ledger_scoped(client: TestClient, *, identity) -> None:
    # Confirm one expense in each ledger so both have CSV-eligible rows.
    owner_id = upload_png(client, identity=identity)
    tester_id = _gray_pending_id(client, identity=identity)
    assert patch_expense(
        client, owner_id, headers=identity.app_headers,
        fields={"amount_cents": 1234, "category": "餐饮"},
    ).status_code == 200
    assert patch_expense(
        client, tester_id, headers=identity.gray_app_headers,
        fields={"amount_cents": 5678, "category": "餐饮"},
    ).status_code == 200
    assert confirm_expense_api(client, owner_id, headers=identity.app_headers).status_code == 200
    assert confirm_expense_api(
        client, tester_id, headers=identity.gray_app_headers
    ).status_code == 200

    owner_csv = client.get("/api/expenses/export.csv", headers=identity.app_headers)
    tester_csv = client.get("/api/expenses/export.csv", headers=identity.gray_app_headers)
    assert owner_csv.status_code == 200
    assert tester_csv.status_code == 200
    # The expense ids appear as the first cell of each data row.
    assert f"\n{owner_id}," in owner_csv.text or f"\r\n{owner_id}," in owner_csv.text
    assert f"\n{tester_id}," not in owner_csv.text and f"\r\n{tester_id}," not in owner_csv.text
    assert f"\n{tester_id}," in tester_csv.text or f"\r\n{tester_id}," in tester_csv.text
    assert f"\n{owner_id}," not in tester_csv.text and f"\r\n{owner_id}," not in tester_csv.text


def test_monthly_stats_is_ledger_scoped(client: TestClient, *, identity) -> None:
    # Confirm one expense per ledger; the monthly total should differ by ledger.
    owner_id = upload_png(client, identity=identity)
    tester_id = _gray_pending_id(client, identity=identity)
    assert patch_expense(
        client, owner_id, headers=identity.app_headers,
        fields={"amount_cents": 1234, "category": "餐饮"},
    ).status_code == 200
    assert patch_expense(
        client, tester_id, headers=identity.gray_app_headers,
        fields={"amount_cents": 5678, "category": "餐饮"},
    ).status_code == 200
    assert confirm_expense_api(client, owner_id, headers=identity.app_headers).status_code == 200
    assert confirm_expense_api(
        client, tester_id, headers=identity.gray_app_headers
    ).status_code == 200

    owner_stats = client.get("/api/stats/monthly", headers=identity.app_headers)
    tester_stats = client.get("/api/stats/monthly", headers=identity.gray_app_headers)
    assert owner_stats.status_code == 200 and tester_stats.status_code == 200
    # Each ledger reports only its own confirmed amount.
    assert owner_stats.json()["total_amount_cents"] == 1234
    assert tester_stats.json()["total_amount_cents"] == 5678
    # Sanity: pending list never sees the other ledger's id even after confirm.
    other_pending = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert all(row["id"] != tester_id for row in other_pending.json())
