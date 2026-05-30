"""LAN-IP selection — the pure ranking/filter, independent of OS enumeration."""

from __future__ import annotations

from backend_manager.netinfo import _pick_lan_ip


def test_clash_fake_ip_is_rejected() -> None:
    assert _pick_lan_ip(["198.18.0.1"]) is None


def test_prefers_192_168_over_10() -> None:
    assert _pick_lan_ip(["10.0.0.5", "192.168.1.42"]) == "192.168.1.42"


def test_prefers_172_over_10() -> None:
    assert _pick_lan_ip(["10.0.0.5", "172.20.1.1"]) == "172.20.1.1"


def test_cgnat_linklocal_loopback_rejected() -> None:
    assert _pick_lan_ip(["100.64.1.1", "169.254.1.1", "127.0.0.1"]) is None


def test_picks_real_lan_over_proxy_fake_ip() -> None:
    assert _pick_lan_ip(["198.18.0.1", "192.168.1.7"]) == "192.168.1.7"


def test_ignores_garbage_entries() -> None:
    assert _pick_lan_ip(["not-an-ip", "", "192.168.0.9"]) == "192.168.0.9"
