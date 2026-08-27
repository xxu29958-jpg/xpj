from __future__ import annotations

import io
import socket
import time
from http.client import HTTPConnection, HTTPException, HTTPResponse

from ticketbox_lifecycle.errors import LifecycleError

_BODY_LIMIT_BYTES = 16 * 1024
_READ_CHUNK_BYTES = 4 * 1024
_TOTAL_TIMEOUT_SECONDS = 5


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("installation health response deadline elapsed")
    return remaining


class _DeadlineReader(io.RawIOBase):
    def __init__(self, network_socket: socket.socket, deadline: float) -> None:
        self._network_socket = network_socket
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:
        self._network_socket.settimeout(_remaining_seconds(self._deadline))
        return self._network_socket.recv_into(buffer)


class _DeadlineSocket:
    def __init__(self, network_socket: socket.socket, deadline: float) -> None:
        self._network_socket = network_socket
        self._deadline = deadline

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("installation health transport is read-only")
        return io.BufferedReader(_DeadlineReader(self._network_socket, self._deadline))


def _read_body(response: HTTPResponse, *, deadline: float) -> bytes:
    body = bytearray()
    while True:
        _remaining_seconds(deadline)
        remaining = _BODY_LIMIT_BYTES + 1 - len(body)
        try:
            chunk = response.read1(min(_READ_CHUNK_BYTES, remaining))
        except TimeoutError as exc:
            raise LifecycleError(
                "health_unreachable",
                "installation health response deadline elapsed",
            ) from exc
        except (OSError, HTTPException) as exc:
            raise LifecycleError(
                "health_unreachable",
                "installation health transport failed",
            ) from exc
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > _BODY_LIMIT_BYTES:
            raise LifecycleError(
                "health_identity_mismatch",
                "installation health response is too large",
            )


def fetch_installation_health(backend_port: int, *, challenge: str) -> tuple[int, bytes, str | None]:
    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    connection = HTTPConnection("127.0.0.1", backend_port, timeout=_remaining_seconds(deadline))
    network_socket: socket.socket | None = None
    response: HTTPResponse | None = None
    try:
        connection.connect()
        if connection.sock is None:
            raise OSError("installation health connection has no socket")
        network_socket = connection.sock
        network_socket.settimeout(_remaining_seconds(deadline))
        connection.request(
            "GET",
            "/api/health/installation",
            headers={
                "Accept": "application/json",
                "Connection": "close",
                "X-Ticketbox-Health-Challenge": challenge,
            },
        )
        connection.sock = None
        response = HTTPResponse(_DeadlineSocket(network_socket, deadline), method="GET")
        response.begin()
        body = b"" if response.status != 200 else _read_body(response, deadline=deadline)
        return response.status, body, response.getheader("X-Ticketbox-Health-Attestation")
    except TimeoutError as exc:
        raise LifecycleError(
            "health_unreachable",
            "installation health response deadline elapsed",
        ) from exc
    except (OSError, HTTPException) as exc:
        raise LifecycleError(
            "health_unreachable",
            "installation health transport failed",
        ) from exc
    finally:
        if response is not None:
            response.close()
        if network_socket is not None:
            network_socket.close()
        connection.close()
