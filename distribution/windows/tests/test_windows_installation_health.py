from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from http.client import IncompleteRead

import pytest
from ticketbox_lifecycle.errors import LifecycleError
from ticketbox_lifecycle.runtime import windows_installation_health as health


class _HealthResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

    def read1(self, size: int) -> bytes:
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


@contextmanager
def _health_server(body: bytes, *, header_delay_seconds: float = 0.0):
    headers = (
        b"HTTP/1.1 200 OK\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"Content-Type: application/json\r\n\r\n"
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    stop = threading.Event()

    def serve() -> None:
        connection, _address = listener.accept()
        with connection:
            try:
                connection.settimeout(1)
                request = bytearray()
                while b"\r\n\r\n" not in request and len(request) <= 8 * 1024:
                    chunk = connection.recv(1024)
                    if not chunk:
                        return
                    request.extend(chunk)
                if b"\r\n\r\n" not in request:
                    return
                if header_delay_seconds:
                    for byte in headers:
                        if stop.wait(header_delay_seconds):
                            return
                        connection.sendall(bytes((byte,)))
                else:
                    connection.sendall(headers)
                connection.sendall(body)
            except OSError:
                return

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        listener.close()
        server.join(timeout=1)


def test_health_transport_reads_fixed_loopback_response(monkeypatch) -> None:
    body = b'{"contract":"ticketbox-installation-health-v3"}'
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)

    with _health_server(body) as port:
        status, observed, attestation = health.fetch_installation_health(port, challenge="a" * 64)

    assert status == 200
    assert observed == body
    assert attestation is None


def test_health_transport_rejects_oversized_response() -> None:
    body = b"x" * (health._BODY_LIMIT_BYTES + 1)

    with pytest.raises(LifecycleError) as caught:
        health._read_body(
            _HealthResponse(body),
            deadline=time.monotonic() + 1,
        )

    assert caught.value.code == "health_identity_mismatch"
    assert caught.value.message == "installation health response is too large"


def test_health_transport_normalizes_body_failure() -> None:
    class IncompleteResponse(_HealthResponse):
        def read1(self, size: int) -> bytes:
            del size
            raise IncompleteRead(b"{", 1)

    with pytest.raises(LifecycleError) as caught:
        health._read_body(
            IncompleteResponse(b""),
            deadline=time.monotonic() + 1,
        )

    assert caught.value.code == "health_unreachable"


def test_health_transport_deadline_includes_status_and_headers(monkeypatch) -> None:
    body = b'{"contract":"ticketbox-installation-health-v3"}'
    monkeypatch.setattr(health, "_TOTAL_TIMEOUT_SECONDS", 0.15)
    started = time.monotonic()

    with (
        _health_server(body, header_delay_seconds=0.02) as port,
        pytest.raises(LifecycleError) as caught,
    ):
        health.fetch_installation_health(port, challenge="a" * 64)

    assert caught.value.code == "health_unreachable"
    assert caught.value.message == "installation health response deadline elapsed"
    assert time.monotonic() - started < 1
