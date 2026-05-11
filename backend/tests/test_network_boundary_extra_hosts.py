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
