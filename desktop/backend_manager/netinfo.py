"""Real LAN IPv4 discovery for the status display.

On a machine running Clash/a full-tunnel VPN, the routing layer is hijacked: every
``socket`` route (even to LAN-range targets) resolves to the proxy's fake-IP gateway
(198.18.x), so socket-based detection never sees the real LAN address. We therefore
ENUMERATE ADAPTERS (via ``psutil``, which reads each interface's own unicast IPs and
bypasses routing) and pick a genuine RFC1918 LAN address, skipping proxy / CGNAT /
link-local ranges. ``psutil`` is optional: if absent we fall back to hostname
resolution (correct on a normal machine, ``None`` behind a full tunnel).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable

# Preferred real-LAN networks, in priority order (a typical home is 192.168.*).
_REAL_LAN_NETS = (
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("10.0.0.0/8"),
)


def _pick_lan_ip(candidates: Iterable[str]) -> str | None:
    """Pick the best real-LAN IPv4 from ``candidates`` (192.168 > 172.16-31 > 10).

    Proxy fake-IP (198.18/15), CGNAT (100.64/10), link-local (169.254) and loopback
    are excluded by virtue of not being a member of any ``_REAL_LAN_NETS`` network.
    """
    best: str | None = None
    best_rank = len(_REAL_LAN_NETS)
    for raw in candidates:
        try:
            addr = ipaddress.IPv4Address(raw)
        except ipaddress.AddressValueError:
            continue
        for rank, net in enumerate(_REAL_LAN_NETS):
            if addr in net and rank < best_rank:
                best, best_rank = raw, rank
    return best


def _socket_ipv4s() -> list[str]:
    """Fallback enumeration via hostname resolution (blind behind a full tunnel)."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [info[4][0] for info in infos]


def _enumerate_ipv4() -> list[str]:
    """Every local IPv4, read per-adapter (psutil) so a hijacked route table can't hide the LAN IP."""
    try:
        import psutil
    except ImportError:
        return _socket_ipv4s()
    addresses: list[str] = []
    for adapter_addrs in psutil.net_if_addrs().values():
        for addr in adapter_addrs:
            if addr.family == socket.AF_INET and addr.address:
                addresses.append(addr.address)
    return addresses or _socket_ipv4s()


def lan_ip() -> str | None:
    """A real LAN IPv4 (192.168 > 172.16-31 > 10), or ``None`` if none is found."""
    return _pick_lan_ip(_enumerate_ipv4())
