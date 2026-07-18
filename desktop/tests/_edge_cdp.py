"""Tiny dependency-free CDP client for the Windows Edge layout gate."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import secrets
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from backend_manager.process import WindowsKillOnCloseJob, spawn_windows_job_process

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_EDGE_OPERATION_TIMEOUT_SECONDS = 30.0
_APP_TARGET_STABLE_CLOSED_SECONDS = 0.25


class _DevToolsTransportError(RuntimeError):
    """Raised when a bounded Edge DevTools session cannot carry commands."""


def _remaining_timeout(deadline: float, *, cap: float, message: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _DevToolsTransportError(message)
    return min(cap, max(remaining, 0.001))


class _WebSocket:
    def __init__(
        self,
        url: str,
        *,
        deadline: float | None = None,
        timeout: float = 10.0,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"refusing non-loopback DevTools websocket: {url}")
        self._deadline = deadline
        connect_timeout = (
            timeout
            if deadline is None
            else _remaining_timeout(
                deadline,
                cap=timeout,
                message="Edge operation deadline expired before DevTools connected",
            )
        )
        self._socket = socket.create_connection(
            (parsed.hostname, parsed.port or 80),
            timeout=connect_timeout,
        )
        self._socket.settimeout(connect_timeout)
        self._stream = self._socket.makefile("rb", buffering=0)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port or 80}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        self._refresh_timeout()
        status = self._stream.readline().decode("ascii", errors="replace").strip()
        headers: dict[str, str] = {}
        while True:
            self._refresh_timeout()
            line = self._stream.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
            name, _, value = line.decode("ascii", errors="replace").partition(":")
            headers[name.strip().casefold()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode("ascii")).digest(),  # noqa: S324 - RFC 6455
        ).decode("ascii")
        if status != "HTTP/1.1 101 WebSocket Protocol Handshake" or headers.get(
            "sec-websocket-accept",
        ) != expected:
            self.close()
            raise _DevToolsTransportError(f"DevTools websocket handshake failed: {status}")
        self._next_id = 1

    def _refresh_timeout(self) -> None:
        if self._deadline is not None:
            self._socket.settimeout(
                _remaining_timeout(
                    self._deadline,
                    cap=10.0,
                    message="Edge operation deadline expired during DevTools transport",
                ),
            )

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            self._socket.close()

    def _send_frame(self, payload: bytes, *, opcode: int = 1) -> None:
        self._refresh_timeout()
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._socket.sendall(header + encoded)

    def _read_exact(self, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            self._refresh_timeout()
            chunk = self._stream.read(remaining)
            if not chunk:
                raise _DevToolsTransportError("DevTools websocket closed unexpectedly")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _receive_json(self) -> dict[str, object]:
        fragments = bytearray()
        while True:
            first, second = self._read_exact(2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            masked = bool(second & 0x80)
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 8:
                raise _DevToolsTransportError(
                    "DevTools websocket closed before returning a response",
                )
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode in {0, 1}:
                fragments.extend(payload)
                if final:
                    value = json.loads(fragments.decode("utf-8"))
                    assert isinstance(value, dict)
                    return value

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        request_id = self._next_id
        self._next_id += 1
        self._send_frame(
            json.dumps(
                {"id": request_id, "method": method, "params": params or {}},
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        while True:
            response = self._receive_json()
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise AssertionError(f"DevTools {method} failed: {response['error']}")
            result = response.get("result", {})
            assert isinstance(result, dict)
            return result


def _wait_for_devtools(
    profile: Path,
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
) -> tuple[int, str]:
    active_port = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        try:
            lines = active_port.read_text(encoding="ascii").splitlines()
        except OSError:
            lines = []
        if len(lines) >= 2:
            return int(lines[0]), lines[1]
        return_code = process.poll()
        if return_code is not None:
            raise _DevToolsTransportError(
                f"Edge exited before publishing DevToolsActivePort (exit={return_code})",
            )
        time.sleep(0.05)
    raise _DevToolsTransportError(
        f"Edge did not publish DevToolsActivePort (launcher exit={process.poll()})",
    )


def _page_websocket(
    port: int,
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(
                f"http://127.0.0.1:{port}/json/list",
                timeout=_remaining_timeout(
                    deadline,
                    cap=1.0,
                    message="Edge operation deadline expired before page discovery",
                ),
            ) as response:
                targets = json.loads(response.read())
        except (OSError, ValueError):
            return_code = process.poll()
            if return_code is not None:
                raise _DevToolsTransportError(
                    f"Edge exited before exposing a page DevTools target (exit={return_code})",
                ) from None
            time.sleep(0.05)
            continue
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
    raise _DevToolsTransportError("Edge did not expose a page DevTools target")


def _devtools_targets(port: int, *, deadline: float) -> list[dict[str, object]]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(
        f"http://127.0.0.1:{port}/json/list",
        timeout=_remaining_timeout(
            deadline,
            cap=1.0,
            message="Edge app-window deadline expired during target discovery",
        ),
    ) as response:
        targets = json.loads(response.read())
    assert isinstance(targets, list)
    return [target for target in targets if isinstance(target, dict)]


def _close_websocket_safely(websocket: _WebSocket | None) -> None:
    if websocket is None:
        return
    with contextlib.suppress(OSError, ValueError):
        websocket.close()


def _reap_edge_process(
    process: subprocess.Popen[bytes],
    *,
    job: WindowsKillOnCloseJob | None,
) -> None:
    if job is not None:
        job.close()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(OSError):
        process.kill()
    process.wait(timeout=2)


def _app_window_targets_are_closed(
    targets: list[dict[str, object]],
    *,
    target_id: str,
) -> bool:
    page_targets = [target for target in targets if target.get("type") == "page"]
    return not page_targets and all(str(target.get("id")) != target_id for target in targets)


def _edge_process_closed_cleanly(
    process: subprocess.Popen[bytes],
    *,
    target_id: str | None,
) -> bool:
    if target_id is None:
        return False
    return_code = process.poll()
    if return_code is None:
        return False
    if return_code != 0:
        raise AssertionError(
            f"Edge crashed before the app target closed cleanly (exit={return_code})"
        )
    return True


def _launch_edge(edge: str, arguments: list[str]) -> tuple[subprocess.Popen[bytes], WindowsKillOnCloseJob]:
    process, job = spawn_windows_job_process(
        [edge, *arguments],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process, job


def _stop_edge(
    process: subprocess.Popen[bytes],
    *,
    job: WindowsKillOnCloseJob,
    page: _WebSocket | None,
    browser_endpoint: str | None,
) -> None:
    try:
        _close_websocket_safely(page)
        browser: _WebSocket | None = None
        try:
            if browser_endpoint is not None:
                browser = _WebSocket(browser_endpoint)
                browser.request("Browser.close")
        except (AssertionError, OSError, _DevToolsTransportError):
            pass
        finally:
            _close_websocket_safely(browser)
    finally:
        _reap_edge_process(process, job=job)


def evaluate_page(
    edge: str,
    *,
    profile: Path,
    url: str,
    width: int,
    height: int,
    expression: str,
) -> object:
    deadline = time.monotonic() + _EDGE_OPERATION_TIMEOUT_SECONDS
    profile.mkdir(parents=True)
    process, job = _launch_edge(
        edge,
        [
            "--edge-skip-compat-layer-relaunch",
            "--headless=new",
            "--disable-background-networking",
            "--disable-gpu",
            "--no-first-run",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
    )
    page: _WebSocket | None = None
    browser_endpoint: str | None = None
    try:
        port, browser_path = _wait_for_devtools(profile, process, deadline=deadline)
        browser_endpoint = f"ws://127.0.0.1:{port}{browser_path}"
        page = _WebSocket(
            _page_websocket(port, process, deadline=deadline),
            deadline=deadline,
        )
        page.request(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        page.request("Page.navigate", {"url": url})
        while time.monotonic() < deadline:
            evaluated = page.request(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
            )
            remote = evaluated.get("result", {})
            if isinstance(remote, dict) and remote.get("type") != "undefined":
                return remote.get("value")
            time.sleep(0.05)
        raise AssertionError("layout probe did not become available")
    finally:
        _stop_edge(process, job=job, page=page, browser_endpoint=browser_endpoint)


def wait_for_app_window_close(edge: str, *, profile: Path, url: str) -> None:
    """Verify that a real Edge app target closes itself after rendering the page."""
    deadline = time.monotonic() + _EDGE_OPERATION_TIMEOUT_SECONDS
    profile.mkdir(parents=True)
    process, job = _launch_edge(
        edge,
        [
            "--edge-skip-compat-layer-relaunch",
            "--disable-background-mode",
            "--disable-background-networking",
            "--no-first-run",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            f"--app={url}",
            "--window-size=820,660",
        ],
    )
    browser_endpoint: str | None = None
    try:
        port, browser_path = _wait_for_devtools(profile, process, deadline=deadline)
        browser_endpoint = f"ws://127.0.0.1:{port}{browser_path}"
        target_id: str | None = None
        closed_since: float | None = None
        while time.monotonic() < deadline:
            if _edge_process_closed_cleanly(process, target_id=target_id):
                return
            try:
                targets = _devtools_targets(port, deadline=deadline)
            except (OSError, ValueError):
                if _edge_process_closed_cleanly(process, target_id=target_id):
                    return
                time.sleep(0.05)
                continue
            if target_id is None:
                matching = next(
                    (
                        target
                        for target in targets
                        if target.get("type") == "page"
                        and target.get("url") == url
                        and isinstance(target.get("id"), str)
                    ),
                    None,
                )
                if matching is not None:
                    target_id = str(matching["id"])
                time.sleep(0.05)
                continue
            if _app_window_targets_are_closed(targets, target_id=target_id):
                now = time.monotonic()
                closed_since = closed_since or now
                if now - closed_since >= _APP_TARGET_STABLE_CLOSED_SECONDS:
                    return
            else:
                closed_since = None
            time.sleep(0.05)
        raise AssertionError("Edge app window did not close after Manager maintenance state")
    finally:
        _stop_edge(process, job=job, page=None, browser_endpoint=browser_endpoint)
