"""Tests for XPJ_EXTRA_LOOPBACK_HOSTS env var (used by capture scripts)."""

from __future__ import annotations

import pytest
from fastapi import Request

from app.errors import AppError
from app.network_boundary import is_loopback_request, require_owner_console_local


def _make_request(host: str, *, peer: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"host", host.encode("latin1"))],
        "client": (peer, 12345),
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


def test_base_loopback_hosts_accepted() -> None:
    assert is_loopback_request(_make_request("127.0.0.1:8000"))
    assert is_loopback_request(_make_request("localhost"))


def test_unknown_port_rejected_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XPJ_EXTRA_LOOPBACK_HOSTS", raising=False)
    assert not is_loopback_request(_make_request("127.0.0.1:8765"))
    with pytest.raises(AppError):
        require_owner_console_local(_make_request("127.0.0.1:8765"))


def test_extra_loopback_hosts_env_var_allows_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "XPJ_EXTRA_LOOPBACK_HOSTS", "127.0.0.1:8765, localhost:8765 "
    )
    assert is_loopback_request(_make_request("127.0.0.1:8765"))
    assert is_loopback_request(_make_request("localhost:8765"))
    # Still rejects non-loopback peer.
    assert not is_loopback_request(_make_request("127.0.0.1:8765", peer="10.0.0.5"))


def test_extra_loopback_hosts_does_not_widen_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XPJ_EXTRA_LOOPBACK_HOSTS", "127.0.0.1:8765")
    # Cloudflare Tunnel forwards public hostnames; those must remain rejected
    # even with extra ports configured.
    assert not is_loopback_request(_make_request("api.zen70.cn"))


def test_empty_env_var_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XPJ_EXTRA_LOOPBACK_HOSTS", "")
    assert not is_loopback_request(_make_request("127.0.0.1:8765"))
    assert is_loopback_request(_make_request("127.0.0.1:8000"))


def test_extra_loopback_hosts_rejects_public_dns_entry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    # An operator who pastes the Cloudflare Tunnel hostname into this env var
    # by mistake must NOT silently widen /web / /owner. Only loopback-style
    # entries take effect; non-loopback entries are dropped with log.error.
    monkeypatch.setenv("XPJ_EXTRA_LOOPBACK_HOSTS", "api.example.com, 127.0.0.1:8765")
    with caplog.at_level("ERROR", logger="app.network_boundary"):
        # The accepted port still works.
        assert is_loopback_request(_make_request("127.0.0.1:8765"))
        # The rejected DNS entry must NOT bypass the boundary just because
        # someone configured it.
        assert not is_loopback_request(_make_request("api.example.com"))
    assert any("XPJ_EXTRA_LOOPBACK_HOSTS" in record.message for record in caplog.records)
    # Verify the dropped host literal appears in the logger.error args (logger
    # call is ``logger.error(..., rejected)`` with rejected being a list).
    # Written as ``any(item == EXPECTED)`` rather than ``EXPECTED in collection``
    # because CodeQL's py/incomplete-url-substring-sanitization syntactically
    # matches the latter pattern as lax URL validation, which this is not —
    # it's a log-content assertion in a test.
    expected_rejected_host = "api.example.com"
    rejected_args = [arg for record in caplog.records for arg in (record.args or ())]
    flat = [str(a) for nested in rejected_args for a in (nested if isinstance(nested, list) else [nested])]
    assert any(item == expected_rejected_host for item in flat), flat


def test_extra_loopback_hosts_rejects_ip_outside_loopback_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Routable IP (LAN or public) — also rejected, even though it's a literal
    # IP and not a DNS name.
    monkeypatch.setenv("XPJ_EXTRA_LOOPBACK_HOSTS", "10.0.0.5:8000, 192.168.1.5")
    assert not is_loopback_request(_make_request("10.0.0.5:8000"))
    assert not is_loopback_request(_make_request("192.168.1.5"))
