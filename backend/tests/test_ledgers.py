"""Tests for v0.4-alpha1 multi-ledger HTTP API and Owner Console pages.

Covers:
* GET  /api/ledgers              — list visible ledgers
* POST /api/ledgers              — owner-only create
* POST /api/ledgers/{id}/switch  — token rotation, membership enforcement,
                                   old-token revocation
* GET/POST /owner/ledgers        — local-only management page
* GET/POST /owner/pairing        — ledger dropdown + selected ledger persists
                                   into the issued PairingCode

Anti-cross-ledger guarantees are tested in
``test_multi_ledger_isolation.py``; this file focuses on the API surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local as _owner_console_require_local
from app.routes.owner_ledgers import _require_local as _owner_ledgers_require_local


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """Test client with the Owner Console loopback dependency bypassed."""
    app.dependency_overrides[_owner_console_require_local] = lambda: None
    app.dependency_overrides[_owner_ledgers_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_owner_console_require_local, None)
    app.dependency_overrides.pop(_owner_ledgers_require_local, None)


def test_list_ledgers_returns_active_memberships(client: TestClient, *, identity) -> None:
    response = client.get("/api/ledgers", headers=identity.app_headers)
    assert response.status_code == 200
    body = response.json()
    assert "ledgers" in body
    ids = {row["ledger_id"] for row in body["ledgers"]}
    # Owner token sees only the ledgers it has membership in. Conftest
    # bootstraps the owner account into both "owner" and "tester_1".
    assert "owner" in ids
    assert "tester_1" in ids
    # Default ledger sorts first.
    assert body["ledgers"][0]["ledger_id"] == "owner"
    assert body["ledgers"][0]["is_default"] is True
    # Internal autoincrement ids must never leak.
    for row in body["ledgers"]:
        assert "id" not in row
        assert isinstance(row["ledger_id"], str)
        assert row["ledger_id"]
        assert row["role"] in {"owner", "member"}


def test_list_ledgers_requires_app_token(client: TestClient) -> None:
    assert client.get("/api/ledgers").status_code == 401
    assert client.get(
        "/api/ledgers", headers={"Authorization": "Bearer not-a-real-token"}
    ).status_code == 401


def test_create_ledger_with_admin_token_adds_membership(client: TestClient, *, identity) -> None:
    response = client.post(
        "/api/ledgers", headers=identity.admin_headers, json={"name": "家庭账本"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "家庭账本"
    assert body["role"] == "owner"
    assert body["is_default"] is False
    new_id = body["ledger_id"]
    assert new_id.startswith("ledger_")

    # The list endpoint now includes the new ledger for the same account.
    listed = client.get("/api/ledgers", headers=identity.app_headers).json()["ledgers"]
    assert any(row["ledger_id"] == new_id for row in listed)


def test_create_ledger_validates_name(client: TestClient, *, identity) -> None:
    blank = client.post("/api/ledgers", headers=identity.admin_headers, json={"name": "  "})
    assert blank.status_code == 422
    assert blank.json()["error"] == "ledger_name_required"

    too_long = client.post(
        "/api/ledgers", headers=identity.admin_headers, json={"name": "x" * 200}
    )
    # Pydantic catches length first (max_length=60) and returns invalid_request.
    assert too_long.status_code == 422


def test_create_ledger_requires_owner_or_admin(client: TestClient) -> None:
    # The conftest "tester_1" app token is bound to a ledger where the
    # owner-account is also owner, so this token *does* satisfy the
    # owner-or-admin rule. Use an unauthenticated request to assert auth.
    response = client.post("/api/ledgers", json={"name": "x"})
    assert response.status_code == 401


def test_switch_ledger_rotates_token_and_revokes_old(client: TestClient, *, identity) -> None:
    # First, create a fresh second ledger via admin.
    create = client.post(
        "/api/ledgers", headers=identity.admin_headers, json={"name": "家庭账本"}
    )
    assert create.status_code == 201
    target_id = create.json()["ledger_id"]

    # Add the owner account as member of the new ledger via direct DB —
    # create_ledger already inserts the owner as member. We rely on that.
    # The current app token is bound to ledger "owner". Switch to target.
    switch = client.post(
        f"/api/ledgers/{target_id}/switch", headers=identity.app_headers
    )
    assert switch.status_code == 200, switch.json()
    body = switch.json()
    new_token = body["session_token"]
    assert new_token and new_token != ""
    assert body["ledger"]["ledger_id"] == target_id
    assert body["ledger"]["name"] == "家庭账本"
    assert body["ledger"]["is_default"] is False

    # Old token is revoked: subsequent calls fail with 401.
    old = client.get("/api/expenses/pending", headers=identity.app_headers)
    assert old.status_code == 401
    stale_switch = client.post(f"/api/ledgers/{target_id}/switch", headers=identity.app_headers)
    assert stale_switch.status_code == 401

    # New token works and points at the new ledger.
    new_headers = {"Authorization": f"Bearer {new_token}"}
    pending = client.get("/api/expenses/pending", headers=new_headers)
    assert pending.status_code == 200
    assert pending.json() == []  # fresh ledger, nothing here

    check = client.get("/api/auth/check", headers=new_headers)
    assert check.status_code == 200
    assert check.json()["ledger_name"] == "家庭账本"


def test_switch_ledger_blocks_non_member(client: TestClient, *, identity) -> None:
    # tester_1 token's account *is* the owner account in conftest, which is
    # also a member of "owner" — so we craft a non-membership scenario by
    # asking app_headers (bound to "owner") to switch to a fabricated id.
    response = client.post(
        "/api/ledgers/ledger_does_not_exist/switch", headers=identity.app_headers
    )
    assert response.status_code == 403
    assert response.json()["error"] == "ledger_forbidden"


def test_switch_ledger_requires_app_token(client: TestClient) -> None:
    response = client.post("/api/ledgers/owner/switch")
    assert response.status_code == 401


def test_owner_pairing_renders_ledger_dropdown(local_client: TestClient) -> None:
    response = local_client.get("/owner/pairing")
    assert response.status_code == 200
    html = response.text
    # The dropdown must be rendered with both seeded ledgers.
    assert 'name="ledger_id"' in html
    assert "我的小票夹" in html
    assert "灰度用户1" in html


def test_owner_pairing_post_uses_selected_ledger(local_client: TestClient) -> None:
    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": "tester_1", "ttl_minutes": "10"},
    )
    assert response.status_code == 200
    html = response.text
    # The success card shows the chosen ledger name (not the default one).
    assert "灰度用户1" in html
    # Eight-digit pairing code is rendered.
    import re

    codes = re.findall(r"\b\d{8}\b", html)
    assert codes, "expected an 8-digit pairing code in the page"


def test_owner_pairing_post_rejects_unknown_ledger(local_client: TestClient) -> None:
    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": "ledger_unknown", "ttl_minutes": "10"},
    )
    assert response.status_code == 200
    # Page renders an error and does not produce a code for the bogus id.
    assert "请选择一个有权限的账本" in response.text


def test_owner_ledgers_lists_and_creates(local_client: TestClient) -> None:
    listing = local_client.get("/owner/ledgers")
    assert listing.status_code == 200
    assert "我的小票夹" in listing.text
    assert "灰度用户1" in listing.text
    assert 'class="skip-link" href="#main-content"' in listing.text
    assert 'class="owner-main" id="main-content" tabindex="-1"' in listing.text
    # Console shows the current household-management advisory banner.
    assert "v0.5" in listing.text
    assert "家庭成员邀请、角色调整和拥有者转让" in listing.text
    assert 'class="role-chip role-owner"' in listing.text
    assert "拥有者" in listing.text
    # Each ledger row exposes a "打开账本" link carrying its ledger_id.
    assert 'href="/web?ledger_id=owner"' in listing.text
    assert "打开账本" in listing.text
    assert 'data-confirm="归档账本' in listing.text
    assert "return confirm(" not in listing.text

    create = local_client.post("/owner/ledgers", data={"name": "家庭账本"})
    assert create.status_code in (200, 303)

    after = local_client.get("/owner/ledgers")
    assert "家庭账本" in after.text
    assert 'data-confirm="归档账本' in after.text
    import re

    archive_action = (
        r"<tr>.*?家庭账本.*?"
        r'action="/owner/ledgers/([^"]+)/archive"'
    )
    match = re.search(archive_action, after.text, re.S)
    assert match is not None
    archive = local_client.post(f"/owner/ledgers/{match.group(1)}/archive")
    assert archive.status_code in (200, 303)

    archived = local_client.get("/owner/ledgers")
    assert archived.status_code == 200
    assert 'data-confirm="恢复账本' in archived.text
    assert "return confirm(" not in archived.text


def test_owner_ledgers_no_secret_leak(local_client: TestClient, *, identity) -> None:
    """The /owner/ledgers page must not echo runtime tokens or absolute paths."""
    import re
    resp = local_client.get("/owner/ledgers")
    assert resp.status_code == 200
    body = resp.text
    assert identity.upload_key not in body
    assert identity.app_token not in body
    assert identity.admin_token not in body
    assert not re.search(r"\b[0-9a-f]{64}\b", body)


def test_owner_ledgers_rejects_blank_name(local_client: TestClient) -> None:
    create = local_client.post("/owner/ledgers", data={"name": "   "})
    # Page re-renders with banner — must NOT 5xx, must NOT redirect.
    assert create.status_code == 200
    assert "请填写账本名称" in create.text


def test_owner_ledgers_remote_returns_403(client: TestClient) -> None:
    # Default test client host is 'testclient' which is rejected.
    assert client.get("/owner/ledgers").status_code == 403
    assert client.post("/owner/ledgers", data={"name": "x"}).status_code == 403
