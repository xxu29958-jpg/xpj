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

from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.errors import AppError
from app.main import app
from app.models import Account, Ledger
from app.routes.owner_console import _pairing as owner_pairing_route
from app.routes.owner_console import _require_local as _owner_console_require_local
from app.routes.owner_ledgers import _require_local as _owner_ledgers_require_local
from app.services import ledger_service


class _PairingPageProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.copy_server_urls: list[str] = []
        self.text_nodes: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        server_url = dict(attrs).get("data-copy-server-url")
        if server_url is not None:
            self.copy_server_urls.append(server_url)

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.text_nodes.append(text)


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


def test_new_ledger_id_batches_collision_checks(monkeypatch: pytest.MonkeyPatch, *, identity) -> None:
    def set_token_hex_values(values: list[str]) -> None:
        generated = iter(values)
        monkeypatch.setattr(ledger_service.secrets, "token_hex", lambda _bytes: next(generated))

    with SessionLocal() as db:
        owner_id = db.scalar(select(Account.id).order_by(Account.id.asc()))
        assert owner_id is not None

        db.add(Ledger(ledger_id="ledger_taken", name="Taken", owner_account_id=owner_id))
        db.flush()
        set_token_hex_values(
            ["taken", "free"]
            + [f"unused_{index}" for index in range(ledger_service.LEDGER_ID_ALLOCATION_RETRIES - 2)]
        )
        assert ledger_service._new_ledger_id(db) == "ledger_free"

        colliding_values = [
            f"colliding_{index}" for index in range(ledger_service.LEDGER_ID_ALLOCATION_RETRIES)
        ]
        db.add_all(
            Ledger(ledger_id=f"ledger_{value}", name=f"Taken {index}", owner_account_id=owner_id)
            for index, value in enumerate(colliding_values)
        )
        db.flush()
        set_token_hex_values(colliding_values)
        with pytest.raises(AppError):
            ledger_service._new_ledger_id(db)


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


def test_owner_pairing_renders_ledger_dropdown(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url="https://finance.example.test",
        ),
    )
    response = local_client.get("/owner/pairing")
    assert response.status_code == 200
    html = response.text
    # The dropdown must be rendered with both seeded ledgers.
    assert 'name="ledger_id"' in html
    assert "我的小票夹" in html
    assert "灰度用户1" in html


def test_owner_pairing_shows_the_exact_android_server_address(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "https://finance.example.test"
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url=endpoint,
        ),
    )

    response = local_client.get("/owner/pairing")

    assert response.status_code == 200
    probe = _PairingPageProbe()
    probe.feed(response.text)
    assert endpoint in probe.text_nodes
    assert probe.copy_server_urls == [endpoint]


@pytest.mark.parametrize(
    "server_url",
    (
        "",
        "https://127.0.0.1:8000",
        "https://localhost",
        "https://[::1]:8000",
        "https://127.1",
        "https://2130706433",
        "https://0177.0.0.1",
        "https://0x7f000001",
        "https://[::ffff:127.0.0.1]",
        "https://%31%32%37.0.0.1",
        "https://[::ffff:192.168.1.10]",
        "https://\uff11\uff12\uff17\u3002\uff10\u3002\uff10\u3002\uff11",
        "https://fa\u00df.de",
        "https://example\u200c.test",
        "https://finance.example.test:0",
    ),
)
def test_owner_pairing_refuses_to_issue_code_without_phone_usable_server_address(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    server_url: str,
) -> None:
    issued: list[bool] = []
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url=server_url,
        ),
    )
    monkeypatch.setattr(
        owner_pairing_route.svc,
        "do_create_pairing_code",
        lambda *_args, **_kwargs: issued.append(True),
    )

    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": "tester_1", "ttl_minutes": "10"},
    )

    assert response.status_code == 200
    assert "请先在设置中完成手机连接配置" in response.text
    assert 'action="/owner/pairing"' not in response.text
    assert issued == []


@pytest.mark.parametrize(
    ("channel", "expected", "excluded"),
    [
        ("development", "bootstrap_dev_owner.ps1", "普通修复不会重建身份"),
        ("managed_host", "普通修复不会重建身份", "bootstrap_dev_owner.ps1"),
        ("operator", "联系部署管理员完成初始化", "bootstrap_dev_owner.ps1"),
    ],
)
def test_owner_pairing_empty_state_matches_runtime_recovery_path(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
    expected: str,
    excluded: str,
) -> None:
    monkeypatch.setattr(owner_pairing_route.svc, "list_console_ledger_choices", lambda _db: [])
    monkeypatch.setattr(owner_pairing_route.svc, "get_default_ledger_id", lambda _db: None)
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(owner_recovery_channel=channel, public_base_url=""),
    )

    response = local_client.get("/owner/pairing")

    assert response.status_code == 200
    assert expected in response.text
    assert excluded not in response.text


@pytest.mark.parametrize(
    ("channel", "expected", "excluded"),
    [
        ("development", "bootstrap_dev_owner.ps1", "普通修复不会重建身份"),
        ("managed_host", "普通修复不会重建身份", "bootstrap_dev_owner.ps1"),
        ("operator", "联系部署管理员完成初始化", "bootstrap_dev_owner.ps1"),
    ],
)
def test_owner_pairing_stale_post_matches_runtime_recovery_path(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
    expected: str,
    excluded: str,
) -> None:
    monkeypatch.setattr(owner_pairing_route.svc, "list_console_ledger_choices", lambda _db: [])
    monkeypatch.setattr(owner_pairing_route.svc, "get_owner_account_id", lambda _db: None)
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(owner_recovery_channel=channel, public_base_url=""),
    )

    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": "stale-ledger", "ttl_minutes": "15"},
    )

    assert response.status_code == 200
    assert expected in response.text
    assert excluded not in response.text


def test_owner_pairing_post_uses_selected_ledger(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_reads = 0

    def settings() -> SimpleNamespace:
        nonlocal settings_reads
        settings_reads += 1
        return SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url="https://finance.example.test",
        )

    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        settings,
    )
    response = local_client.post(
        "/owner/pairing",
        data={"ledger_id": "tester_1", "ttl_minutes": "10"},
    )
    assert response.status_code == 200
    assert settings_reads == 1
    html = response.text
    # The success card shows the chosen ledger name (not the default one).
    assert "灰度用户1" in html
    # Eight-digit pairing code is rendered.
    import re

    codes = re.findall(r"\b\d{8}\b", html)
    assert codes, "expected an 8-digit pairing code in the page"


def test_owner_pairing_post_rejects_unknown_ledger(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        owner_pairing_route,
        "get_settings",
        lambda: SimpleNamespace(
            owner_recovery_channel="managed_host",
            public_base_url="https://finance.example.test",
        ),
    )
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
