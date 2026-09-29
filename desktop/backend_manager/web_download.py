"""Request-owned bounded download, including cancellation before response headers."""

from __future__ import annotations

import http.client
import select
import socket
import threading
from collections.abc import Iterator
from contextlib import suppress

DOWNLOAD_TIMEOUT_SECONDS = 300
DOWNLOAD_CHUNK_BYTES = 64 * 1024


class DownloadCancelledError(ConnectionError):
    pass


class BridgeDownload:
    def __init__(self, connection: http.client.HTTPConnection, client: socket.socket | None):
        self.connection = connection
        self.backend_socket = connection.sock
        self.response: http.client.HTTPResponse | None = None
        self.cancelled = threading.Event()
        self.stopped = threading.Event()
        self.watcher = None
        if client is not None:
            self.watcher = threading.Thread(target=self._watch_client, args=(client,), daemon=True)
            self.watcher.start()

    def _watch_client(self, client: socket.socket) -> None:
        while not self.stopped.wait(0.1):
            try:
                closed = bool(select.select([client], [], [], 0)[0]) and client.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                closed = True
            if closed:
                self.cancelled.set()
                if self.backend_socket is not None:
                    # shutdown interrupts a header/body read held by HTTPResponse's file handle.
                    with suppress(OSError):
                        self.backend_socket.shutdown(socket.SHUT_RDWR)
                return

    def chunks(self) -> Iterator[bytes]:
        response = self.response
        if response is None:
            raise RuntimeError("Download response has not started")
        while True:
            if self.cancelled.is_set():
                raise DownloadCancelledError
            chunk = response.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                if response.length:
                    raise http.client.IncompleteRead(b"", response.length)
                return
            yield chunk

    def close(self) -> None:
        self.stopped.set()
        if self.watcher is not None:
            self.watcher.join(timeout=1)
        if self.response is not None:
            self.response.close()
        self.connection.close()
