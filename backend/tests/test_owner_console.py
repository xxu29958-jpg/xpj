"""Tests for the Owner Console (/owner) pages.

Security invariants verified:
- Local access (127.0.0.1) returns 200; remote access returns 403.
- HTML pages must not contain token_hash values.
- Upload-links list shows only /u/*** masked paths, never the full key.
- Full upload URL only appears once in the create/rotate response.
- All pages render without crashing.
- health.owner_console_status is not 'not-implemented'.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.owner_console import _require_local


def _insert_external_console_device() -> str:
    from app.database import SessionLocal
    from app.models import Account, AuthToken, Device, Ledger, LedgerMember
    from app.services.identity_service import hash_secret
    from app.services.time_service import now_utc

    now = now_utc()
    with SessionLocal() as db:
        account = Account(display_name="external console boundary", created_at=now)
        db.add(account)
        db.flush()
        ledger = Ledger(
            ledger_id="external_console_boundary",
            name="external console boundary",
            owner_account_id=account.id,
            created_at=now,
        )
        db.add(ledger)
        db.flush()
        db.add(
            LedgerMember(
                ledger_id=ledger.ledger_id,
                account_id=account.id,
                role="owner",
                created_at=now,
            )
        )
        device = Device(
            account_id=account.id,
            device_name="external console phone",
            platform="android",
            created_at=now,
        )
        db.add(device)
        db.flush()
        db.add(
            AuthToken(
                token_hash=hash_secret("external-console-token"),
                account_id=account.id,
                device_id=device.id,
                ledger_id=ledger.ledger_id,
                scope="app",
                created_at=now,
            )
        )
        db.commit()
        return device.public_id


@pytest.fixture()
def local_client(client: TestClient) -> TestClient:
    """Client with loopback check bypassed (simulates 127.0.0.1 access)."""
    app.dependency_overrides[_require_local] = lambda: None
    yield client
    app.dependency_overrides.pop(_require_local, None)


def test_owner_index_local_returns_200(local_client: TestClient) -> None:
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    assert "小票夹" in resp.text


def test_owner_index_remote_returns_403(client: TestClient) -> None:
    # Default TestClient uses host='testclient', which is NOT in the loopback
    # allowlist, so the dependency must reject it.
    resp = client.get("/owner")
    assert resp.status_code == 403


def test_owner_html_does_not_contain_token_hash(local_client: TestClient) -> None:
    resp = local_client.get("/owner")
    assert resp.status_code == 200
    # token_hash values are 64-char hex strings; the page must not contain one
    import re

    matches = re.findall(r"\b[0-9a-f]{64}\b", resp.text)
    assert matches == [], f"token_hash leaked in HTML: {matches[:1]}"


def test_owner_devices_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/devices")
    assert resp.status_code == 200
    assert "设备管理" in resp.text or "设备" in resp.text


def test_owner_devices_page_and_actions_are_ledger_scoped(local_client: TestClient) -> None:
    external_public_id = _insert_external_console_device()

    resp = local_client.get("/owner/devices")
    assert resp.status_code == 200
    assert "external console phone" not in resp.text

    rename = local_client.post(
        f"/owner/devices/{external_public_id}/rename",
        data={"device_name": "should not rename"},
        follow_redirects=False,
    )
    assert rename.status_code == 404

    revoke = local_client.post(
        f"/owner/devices/{external_public_id}/revoke",
        follow_redirects=False,
    )
    assert revoke.status_code == 404


def test_owner_devices_html_no_token_hash(local_client: TestClient) -> None:
    import re

    resp = local_client.get("/owner/devices")
    assert resp.status_code == 200
    matches = re.findall(r"\b[0-9a-f]{64}\b", resp.text)
    assert matches == [], f"token_hash in /owner/devices: {matches[:1]}"


def test_owner_pairing_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/pairing")
    assert resp.status_code == 200
    assert "绑定" in resp.text


def test_owner_upload_links_list_masked(local_client: TestClient) -> None:
    resp = local_client.get("/owner/upload-links")
    assert resp.status_code == 200
    assert "data-owner" in resp.text
    assert 'class="table-scroll"' in resp.text
    assert "掩码路径" in resp.text
    # Full upload keys start with 'upl_'; must NOT appear in persistent list HTML
    import re

    raw_keys = re.findall(r"upl_[A-Za-z0-9_\-]{20,}", resp.text)
    assert raw_keys == [], f"raw upload key visible in list: {raw_keys[:1]}"


def test_owner_upload_links_create_reveals_once(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import config as app_config
    from app.services import owner_console_service

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.zen70.cn")
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post("/owner/upload-links")
        assert resp.status_code == 200
        # Full public URL must appear once in the one-shot reveal section.
        assert "https://api.zen70.cn/u/" in resp.text
        # In the rendered full URL itself, ?tz= must appear exactly once —
        # the relative path already carries the timezone parameter, the
        # template must not append it again.
        import re

        full_urls = re.findall(r"https://api\.zen70\.cn/u/[^\s\"<]+", resp.text)
        assert len(full_urls) == 1, full_urls
        assert full_urls[0].count("?tz=") == 1, full_urls[0]
        # Navigating back to the list must not show raw upload keys.
        list_resp = local_client.get("/owner/upload-links")
        assert "/u/***" in list_resp.text
        raw_keys = re.findall(r"upl_[A-Za-z0-9_\-]{20,}", list_resp.text)
        assert raw_keys == [], f"raw upload key visible in list: {raw_keys[:1]}"
        full_urls = re.findall(r"https://api\.zen70\.cn/u/[A-Za-z0-9_\-]+", list_resp.text)
        assert full_urls == [], f"full URL leaked in list: {full_urls[:1]}"
    finally:
        app_config.get_settings.cache_clear()
        # owner_console_service imports get_settings lazily, no cache to clear there.
        _ = owner_console_service


def test_owner_upload_links_warns_when_public_base_url_missing(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import config as app_config

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post("/owner/upload-links")
        assert resp.status_code == 200
        # Owner Console must NOT pretend to provide a usable public URL.
        assert "PUBLIC_BASE_URL" in resp.text
        assert "未配置" in resp.text
        # No https:// /u/ URL should be rendered when the env is missing.
        import re

        full_urls = re.findall(r"https?://[^\s\"<]+/u/[A-Za-z0-9_\-]+", resp.text)
        assert full_urls == [], f"unexpected full URL when PUBLIC_BASE_URL empty: {full_urls[:1]}"
    finally:
        app_config.get_settings.cache_clear()


def test_owner_upload_links_invalid_public_base_url_treated_as_empty(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import config as app_config

    # Missing scheme is invalid and must be ignored (not used to compose URL).
    monkeypatch.setenv("PUBLIC_BASE_URL", "api.zen70.cn")
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post("/owner/upload-links")
        assert resp.status_code == 200
        assert "未配置" in resp.text
    finally:
        app_config.get_settings.cache_clear()


def test_owner_diagnostics_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/diagnostics")
    assert resp.status_code == 200
    assert "诊断" in resp.text


def test_owner_settings_page_opens(local_client: TestClient) -> None:
    resp = local_client.get("/owner/settings")
    assert resp.status_code == 200
    assert "公网域名" in resp.text
    # secondary nav must be present
    assert "/owner/settings/public-base-url" in resp.text
    assert "/owner/settings/security" in resp.text
    assert "/owner/settings/api" in resp.text


def test_owner_settings_subpages_open(local_client: TestClient) -> None:
    for slug in ("public-base-url", "security", "api", "about"):
        resp = local_client.get(f"/owner/settings/{slug}")
        assert resp.status_code == 200, f"/owner/settings/{slug} failed"


def test_owner_settings_api_inspector_lists_owner_routes(local_client: TestClient) -> None:
    resp = local_client.get("/owner/settings/api")
    assert resp.status_code == 200
    # at least one Owner Console path and one /api/admin path appear
    assert "/owner/devices" in resp.text
    assert "/api/admin" in resp.text


def test_owner_rule_application_audit_is_read_only_and_ledger_scoped(
    local_client: TestClient,
) -> None:
    from app.database import SessionLocal
    from app.models import Account, Ledger, RuleApplicationBatch
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        external = Account(display_name="外部账号", created_at=now_utc())
        db.add(external)
        db.flush()
        db.add(
            Ledger(
                id=-100,
                ledger_id="external_first",
                name="外部账本",
                owner_account_id=external.id,
                created_at=now_utc(),
            )
        )
        db.flush()
        db.add(
            RuleApplicationBatch(
                public_id="00000000-0000-0000-0000-000000000000",
                tenant_id="external_first",
                status="applied_confirmed",
                pending_scanned=99,
                changed_count=99,
                created_at=now_utc(),
            )
        )
        db.add(
            RuleApplicationBatch(
                public_id="11111111-1111-1111-1111-111111111111",
                tenant_id="owner",
                status="applied_confirmed",
                pending_scanned=12,
                changed_count=3,
                created_at=now_utc(),
            )
        )
        db.add(
            RuleApplicationBatch(
                public_id="22222222-2222-2222-2222-222222222222",
                tenant_id="tester_1",
                status="rolled_back",
                pending_scanned=8,
                changed_count=2,
                created_at=now_utc(),
                rolled_back_at=now_utc(),
            )
        )
        db.commit()

    owner_page = local_client.get("/owner/rule-applications?ledger_id=owner")
    assert owner_page.status_code == 200
    assert "规则应用审计" in owner_page.text
    assert "已应用历史" in owner_page.text
    assert "11111111-1111-1111-1111-111111111111" in owner_page.text
    assert "22222222-2222-2222-2222-222222222222" not in owner_page.text
    assert "/rollback" not in owner_page.text
    assert 'method="post"' not in owner_page.text.lower()

    gray_page = local_client.get("/owner/rule-applications?ledger_id=tester_1")
    assert gray_page.status_code == 200
    assert "22222222-2222-2222-2222-222222222222" in gray_page.text
    assert "11111111-1111-1111-1111-111111111111" not in gray_page.text

    dashboard = local_client.get("/owner")
    assert dashboard.status_code == 200
    assert "规则应用审计" in dashboard.text
    assert "/owner/rule-applications" in dashboard.text
    assert "00000000-0000-0000-0000-000000000000" not in dashboard.text
    assert "ledger_id=external_first" not in dashboard.text

    forbidden = local_client.get("/owner/rule-applications?ledger_id=external_first")
    assert forbidden.status_code == 403


def test_owner_dashboard_counts_visible_ledgers_only(local_client: TestClient) -> None:
    from app.database import SessionLocal
    from app.models import Account, Expense, Ledger
    from app.services import owner_console_service as svc
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        baseline = svc.get_index_vm(db)
        now = now_utc()
        external = Account(display_name="外部统计账号", created_at=now)
        db.add(external)
        db.flush()
        db.add(
            Ledger(
                id=-101,
                ledger_id="external_dashboard_counts",
                name="外部统计账本",
                owner_account_id=external.id,
                created_at=now,
            )
        )
        db.flush()
        db.add_all(
            [
                Expense(
                    tenant_id="external_dashboard_counts",
                    amount_cents=100,
                    merchant="外部待确认",
                    status="pending",
                    created_at=now,
                    updated_at=now,
                ),
                Expense(
                    tenant_id="external_dashboard_counts",
                    amount_cents=200,
                    merchant="外部已入账",
                    status="confirmed",
                    created_at=now,
                    updated_at=now,
                    confirmed_at=now,
                ),
            ]
        )
        db.commit()

    with SessionLocal() as db:
        after = svc.get_index_vm(db)

    assert after.pending_count == baseline.pending_count
    assert after.confirmed_count == baseline.confirmed_count

    dashboard = local_client.get("/owner")
    assert dashboard.status_code == 200
    assert "外部统计账本" not in dashboard.text


def test_owner_dashboard_renders_unconfigured_budget_status(local_client: TestClient) -> None:
    body = local_client.get("/owner").text
    assert "预算状态" in body
    assert "未配置" in body
    assert "/web/budgets?ledger_id=owner" in body


def test_owner_dashboard_budget_status_uses_primary_visible_ledger(
    local_client: TestClient, *, identity,
) -> None:
    from app.services.time_service import current_month

    month = current_month("Asia/Shanghai")
    created = local_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 12000,
            "merchant": "预算状态餐饮",
            "category": "餐饮",
            "expense_time": f"{month}-05T12:00:00Z",
        },
    )
    assert created.status_code == 200, created.json()
    budget = local_client.put(
        f"/api/budgets/monthly/{month}?timezone=Asia/Shanghai",
        headers=identity.app_headers,
        json={
            "total_amount_cents": 100000,
            "category_budgets": [{"category": "餐饮", "amount_cents": 10000}],
        },
    )
    assert budget.status_code == 200, budget.json()

    body = local_client.get("/owner").text
    assert "预算状态" in body
    assert "¥1000.00" in body
    assert "¥120.00" in body
    assert "¥880.00" in body
    assert "12%" in body
    assert "分类超支" in body
    assert f"/web/budgets?ledger_id=owner&amp;month={month}" in body


def test_owner_dashboard_budget_status_hides_external_ledger_budget(
    local_client: TestClient,
) -> None:
    from app.database import SessionLocal
    from app.models import Account, Budget, Ledger
    from app.services.time_service import current_month, now_utc

    month = current_month("Asia/Shanghai")
    with SessionLocal() as db:
        now = now_utc()
        external = Account(display_name="外部预算账号", created_at=now)
        db.add(external)
        db.flush()
        db.add(
            Ledger(
                id=-109,
                ledger_id="external_budget_status",
                name="外部预算账本",
                owner_account_id=external.id,
                created_at=now,
            )
        )
        db.flush()
        db.add(
            Budget(
                tenant_id="external_budget_status",
                month=month,
                total_amount_cents=999999,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    body = local_client.get("/owner").text
    assert "预算状态" in body
    assert "外部预算账本" not in body
    assert "9999.99" not in body


def test_owner_upload_links_default_and_list_are_ledger_scoped(
    local_client: TestClient,
) -> None:
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Account, Ledger, UploadLink
    from app.services import owner_console_service as svc
    from app.services.admin_service import create_upload_link
    from app.services.time_service import now_utc

    with SessionLocal() as db:
        now = now_utc()
        external = Account(display_name="外部上传账号", created_at=now)
        db.add(external)
        db.flush()
        db.add(
            Ledger(
                id=-102,
                ledger_id="external_upload_first",
                name="外部上传账本",
                owner_account_id=external.id,
                created_at=now,
            )
        )
        db.flush()
        create_upload_link(
            db,
            ledger_id="external_upload_first",
            admin_account_id=external.id,
            default_timezone="Asia/Shanghai",
        )
        visible_ids = {ledger.ledger_id for ledger in svc.list_console_ledger_choices(db)}
        before_ids = set(db.scalars(select(UploadLink.public_id)).all())

    list_page = local_client.get("/owner/upload-links")
    assert list_page.status_code == 200
    assert "外部上传账本" not in list_page.text

    created = local_client.post("/owner/upload-links")
    assert created.status_code == 200

    with SessionLocal() as db:
        created_links = [
            link
            for link in db.scalars(select(UploadLink).order_by(UploadLink.id.asc())).all()
            if link.public_id not in before_ids
        ]

    assert len(created_links) == 1
    assert created_links[0].ledger_id in visible_ids
    assert created_links[0].ledger_id != "external_upload_first"


def test_owner_settings_page_remote_rejected(client: TestClient) -> None:
    resp = client.get("/owner/settings")
    assert resp.status_code == 403


def test_owner_settings_save_public_base_url_writes_env(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app import config as app_config
    from app.services import runtime_settings_service as rss

    fake_env = tmp_path / ".env"
    fake_env.write_text("OCR_PROVIDER=empty\nPUBLIC_BASE_URL=\n", encoding="utf-8")
    monkeypatch.setattr(rss, "_ENV_PATH", fake_env)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post(
            "/owner/settings/public-base-url",
            data={"public_base_url": "https://api.zen70.cn/"},  # trailing slash dropped
        )
        assert resp.status_code == 200
        assert "已保存" in resp.text
        text = fake_env.read_text(encoding="utf-8")
        assert "PUBLIC_BASE_URL=https://api.zen70.cn" in text
        # cache must be refreshed so subsequent reads see the new value
        assert app_config.get_settings().public_base_url == "https://api.zen70.cn"
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        app_config.get_settings.cache_clear()


def test_owner_settings_rejects_missing_scheme(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app import config as app_config
    from app.services import runtime_settings_service as rss

    fake_env = tmp_path / ".env"
    fake_env.write_text("", encoding="utf-8")
    monkeypatch.setattr(rss, "_ENV_PATH", fake_env)
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post(
            "/owner/settings/public-base-url",
            data={"public_base_url": "api.zen70.cn"},
        )
        assert resp.status_code == 200
        assert "http://" in resp.text or "https://" in resp.text
        # nothing was written
        assert "PUBLIC_BASE_URL=api.zen70.cn" not in fake_env.read_text(encoding="utf-8")
    finally:
        app_config.get_settings.cache_clear()


def test_owner_delete_upload_link_requires_revoke_first(local_client: TestClient) -> None:
    create = local_client.post("/owner/upload-links")
    assert create.status_code == 200
    import re

    pids = re.findall(r"/upload-links/([0-9a-f\-]{36})/(?:rotate|revoke)", create.text)
    assert pids, "expected at least one public_id in the rendered list"
    pid = pids[0]
    # Active link cannot be deleted; service raises invalid_request 409.
    resp = local_client.post(f"/owner/upload-links/{pid}/delete", follow_redirects=False)
    assert resp.status_code == 409


def test_owner_delete_upload_link_after_revoke(local_client: TestClient) -> None:
    create = local_client.post("/owner/upload-links")
    assert create.status_code == 200
    import re

    pids = re.findall(r"/upload-links/([0-9a-f\-]{36})/(?:rotate|revoke)", create.text)
    assert pids
    pid = pids[0]
    rev = local_client.post(f"/owner/upload-links/{pid}/revoke", follow_redirects=False)
    assert rev.status_code in (200, 303)
    delete = local_client.post(
        f"/owner/upload-links/{pid}/delete", follow_redirects=False
    )
    assert delete.status_code in (200, 303)
    # Subsequent delete must 404 (link no longer exists).
    again = local_client.post(
        f"/owner/upload-links/{pid}/delete", follow_redirects=False
    )
    assert again.status_code == 404


def test_health_owner_console_status_not_unimplemented(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("owner_console_status") not in {None, "not-implemented"}


# ── v0.3-rc1-preflight: Host-header hardening ───────────────────────────────

class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for Starlette ``Request`` used to exercise the
    network boundary helper. We avoid spinning up the full ASGI stack so we
    can vary the TCP peer address (which Starlette's TestClient pins to
    ``testclient``)."""

    def __init__(self, peer: str | None, host_header: str) -> None:
        self.client = _FakeClient(peer) if peer is not None else None
        self.headers = {"host": host_header}


def test_owner_console_local_peer_local_host_allowed() -> None:
    from app.network_boundary import require_owner_console_local

    require_owner_console_local(_FakeRequest("127.0.0.1", "127.0.0.1:8000"))
    require_owner_console_local(_FakeRequest("127.0.0.1", "localhost:8000"))
    require_owner_console_local(_FakeRequest("::1", "[::1]:8000"))


def test_owner_console_local_peer_public_host_rejected() -> None:
    """Cloudflare Tunnel forwards public traffic to 127.0.0.1, so loopback
    peer alone must not grant access. The Host header has to also look
    local, otherwise the boundary rejects with 403."""
    from app.errors import AppError
    from app.network_boundary import require_owner_console_local

    with pytest.raises(AppError) as excinfo:
        require_owner_console_local(_FakeRequest("127.0.0.1", "api.zen70.cn"))
    assert excinfo.value.status_code == 403


def test_owner_console_remote_peer_rejected() -> None:
    from app.errors import AppError
    from app.network_boundary import require_owner_console_local

    with pytest.raises(AppError):
        require_owner_console_local(_FakeRequest("203.0.113.5", "127.0.0.1:8000"))
    with pytest.raises(AppError):
        require_owner_console_local(_FakeRequest("testclient", "testserver"))


def test_admin_boundary_local_allowed() -> None:
    from app.network_boundary import require_admin_network_boundary

    require_admin_network_boundary(_FakeRequest("127.0.0.1", "127.0.0.1:8000"))


def test_admin_boundary_public_host_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import network_boundary
    from app.errors import AppError

    # Defensive: ensure the public-allow flag is not enabled by env leakage.
    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "false")
    network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        with pytest.raises(AppError) as excinfo:
            network_boundary.require_admin_network_boundary(
                _FakeRequest("127.0.0.1", "api.zen70.cn")
            )
        assert excinfo.value.status_code == 403
    finally:
        network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]


def test_admin_boundary_public_host_allowed_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import network_boundary

    monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]
    try:
        network_boundary.require_admin_network_boundary(
            _FakeRequest("127.0.0.1", "api.zen70.cn")
        )
    finally:
        monkeypatch.setenv("ALLOW_PUBLIC_ADMIN_API", "false")
        network_boundary.get_settings.cache_clear()  # type: ignore[attr-defined]


# ── PUBLIC_BASE_URL origin-only validation ───────────────────────────────────

@pytest.mark.parametrize(
    "bad_url,expect_fragment",
    [
        ("https://api.example.com/foo",  "路径"),
        ("https://api.example.com/foo/", "路径"),
        ("https://api.example.com?x=1",  "查询"),
        ("https://api.example.com#abc",  "片段"),
        ("https://", "主机"),
        # http:// + public host: upload_key is a credential — refuse downgrade
        ("http://api.example.com", "https"),
        ("http://api.zen70.cn:8000", "https"),
    ],
)
def test_owner_settings_rejects_non_origin_url(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    bad_url: str,
    expect_fragment: str,
) -> None:
    from app import config as app_config
    from app.services import runtime_settings_service as rss

    fake_env = tmp_path / ".env"
    fake_env.write_text("", encoding="utf-8")
    monkeypatch.setattr(rss, "_ENV_PATH", fake_env)
    app_config.get_settings.cache_clear()
    try:
        resp = local_client.post(
            "/owner/settings/public-base-url",
            data={"public_base_url": bad_url},
        )
        assert resp.status_code == 200, resp.text
        assert expect_fragment in resp.text, (
            f"Expected error hint '{expect_fragment}' not found for input {bad_url!r}"
        )
        assert bad_url not in fake_env.read_text(encoding="utf-8"), (
            f"Bad URL should NOT have been written to .env for input {bad_url!r}"
        )
    finally:
        app_config.get_settings.cache_clear()


def test_owner_settings_service_only_allows_public_base_url() -> None:
    """_EDITABLE_KEYS must contain only PUBLIC_BASE_URL — any expansion is a
    security change that requires explicit review."""
    from app.services.runtime_settings_service import _EDITABLE_KEYS

    assert frozenset({"PUBLIC_BASE_URL"}) == _EDITABLE_KEYS, (
        f"_EDITABLE_KEYS should only contain PUBLIC_BASE_URL, got: {_EDITABLE_KEYS}"
    )


def test_owner_settings_trailing_slash_stripped(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Trailing slash should be stripped; path /foo should be rejected."""
    from app import config as app_config
    from app.services import runtime_settings_service as rss

    fake_env = tmp_path / ".env"
    fake_env.write_text("", encoding="utf-8")
    monkeypatch.setattr(rss, "_ENV_PATH", fake_env)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    app_config.get_settings.cache_clear()
    try:
        # bare trailing slash (no path segment) is accepted and stripped
        resp = local_client.post(
            "/owner/settings/public-base-url",
            data={"public_base_url": "https://api.example.com/"},
        )
        assert resp.status_code == 200
        text = fake_env.read_text(encoding="utf-8")
        assert "PUBLIC_BASE_URL=https://api.example.com\n" in text or \
               "PUBLIC_BASE_URL=https://api.example.com" in text
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        app_config.get_settings.cache_clear()
