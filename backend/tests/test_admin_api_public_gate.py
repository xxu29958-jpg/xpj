"""v1.1 Batch 1: ALLOW_PUBLIC_ADMIN_API requires Cloudflare Access.

The startup gate (``_assert_admin_api_gate_safe``) refuses to boot when
the owner opened the admin API to the public hostname without also
turning on Cloudflare Access. The runtime middleware then enforces
JWT verification on every /api/admin/* request.

We test the gate function directly (not via TestClient) because the
test lifespan runs once and the admin API stays loopback-only there.
"""

from __future__ import annotations

import pytest

from app.config import reset_settings_cache
from app.main import _assert_admin_api_gate_safe


@pytest.fixture()
def reset_settings(monkeypatch: pytest.MonkeyPatch):
    yield monkeypatch
    reset_settings_cache()


def test_default_loopback_only_does_not_require_access(
    reset_settings,
) -> None:
    # ALLOW_PUBLIC_ADMIN_API absent → no requirement, no exception.
    reset_settings.delenv("ALLOW_PUBLIC_ADMIN_API", raising=False)
    reset_settings_cache()
    _assert_admin_api_gate_safe()


def test_public_admin_without_access_refuses_boot(reset_settings) -> None:
    reset_settings.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    reset_settings.delenv("CLOUDFLARE_ACCESS_REQUIRED", raising=False)
    reset_settings.delenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN", raising=False)
    reset_settings.delenv("CLOUDFLARE_ACCESS_AUD", raising=False)
    reset_settings_cache()
    with pytest.raises(RuntimeError, match="ALLOW_PUBLIC_ADMIN_API"):
        _assert_admin_api_gate_safe()


def test_public_admin_with_partial_access_refuses_boot(reset_settings) -> None:
    reset_settings.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    reset_settings.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    reset_settings.setenv(
        "CLOUDFLARE_ACCESS_TEAM_DOMAIN", "https://example.cloudflareaccess.com"
    )
    reset_settings.delenv("CLOUDFLARE_ACCESS_AUD", raising=False)
    reset_settings_cache()
    with pytest.raises(RuntimeError, match="CLOUDFLARE_ACCESS_AUD"):
        _assert_admin_api_gate_safe()


def test_public_admin_with_full_access_boots(reset_settings) -> None:
    reset_settings.setenv("ALLOW_PUBLIC_ADMIN_API", "true")
    reset_settings.setenv("CLOUDFLARE_ACCESS_REQUIRED", "true")
    reset_settings.setenv(
        "CLOUDFLARE_ACCESS_TEAM_DOMAIN", "https://example.cloudflareaccess.com"
    )
    reset_settings.setenv("CLOUDFLARE_ACCESS_AUD", "abc123")
    reset_settings_cache()
    _assert_admin_api_gate_safe()
