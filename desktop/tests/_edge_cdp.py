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
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_EVALUATE_PAGE_ATTEMPTS = 2
_PAGE_READY_DIAGNOSTIC = """
(() => {
  const protocols = ["about:", "file:", "http:", "https:", "chrome-error:", "edge-error:"];
  const protocol = protocols.includes(location.protocol) ? location.protocol : "other";
  let route = "other";
  if (protocol === "about:") route = "about";
  else if (protocol === "file:") route = "file";
  else if (location.pathname === "/api/bootstrap") route = "bootstrap";
  else if (location.pathname === "/web") route = "web";
  else if (location.pathname === "/web/pending") route = "pending";
  else if (location.pathname === "/" || location.pathname === "/index.html") route = "manager";
  return {
    protocol, route, readyState: document.readyState,
    mainContent: Boolean(document.querySelector("#main-content")),
    domContentLoaded: (performance.getEntriesByType("navigation")[0]?.domContentLoadedEventEnd ?? 0) > 0,
    stylesReady: Array.from(document.querySelectorAll('link[rel="stylesheet"]')).every(link => link.sheet !== null),
    imagesReady: Array.from(document.images).every(image => image.complete),
    fontsReady: document.fonts.status === "loaded",
    renderProbeStarted: globalThis.__probeStarted === true,
    renderProbeResultReady: typeof globalThis.__probeResult === "string"
  };
})()
"""
_READY_DIAGNOSTIC_VALUES = {
    "protocol": {"about:", "file:", "http:", "https:", "chrome-error:", "edge-error:", "other"},
    "route": {"about", "file", "bootstrap", "web", "pending", "manager", "other"},
    "readyState": {"loading", "interactive", "complete"},
}


class _DevToolsTransportError(RuntimeError):
    """Raised when a bounded Edge DevTools session cannot carry commands."""


class _WebSocket:
    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"refusing non-loopback DevTools websocket: {url}")
        self._socket = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        self._socket.settimeout(timeout)
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
        status = self._stream.readline().decode("ascii", errors="replace").strip()
        headers: dict[str, str] = {}
        while True:
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

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            self._socket.close()

    def _send_frame(self, payload: bytes, *, opcode: int = 1) -> None:
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


def _wait_for_devtools(profile: Path, process: subprocess.Popen[bytes]) -> tuple[int, str]:
    active_port = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            lines = active_port.read_text(encoding="ascii").splitlines()
        except OSError:
            lines = []
        if len(lines) >= 2:
            return int(lines[0]), lines[1]
        time.sleep(0.05)
    raise _DevToolsTransportError(
        f"Edge did not publish DevToolsActivePort (launcher exit={process.poll()})",
    )


def _page_websocket(port: int) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                targets = json.loads(response.read())
        except (OSError, ValueError):
            time.sleep(0.05)
            continue
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
    raise _DevToolsTransportError("Edge did not expose a page DevTools target")


def _devtools_targets(port: int) -> list[dict[str, object]]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
        targets = json.loads(response.read())
    assert isinstance(targets, list)
    return [target for target in targets if isinstance(target, dict)]


def _close_websocket_safely(websocket: _WebSocket | None) -> None:
    if websocket is None:
        return
    with contextlib.suppress(OSError, ValueError):
        websocket.close()


def _reap_edge_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(OSError):
        process.terminate()
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(OSError):
        process.kill()
    process.wait(timeout=5)


def _stop_edge(
    process: subprocess.Popen[bytes],
    *,
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
        _reap_edge_process(process)


def _layout_timeout_diagnostic(
    page: _WebSocket, navigation: dict[str, object], last_remote: object,
) -> dict[str, object]:
    """Observe only fixed enums/booleans; never include browser strings or URLs."""
    remote_type = last_remote.get("type") if isinstance(last_remote, dict) else None
    diagnostic: dict[str, object] = {
        "navigateErrorTextPresent": "errorText" in navigation,
        "navigateIsDownload": navigation.get("isDownload") is True,
        "probeReturnType": remote_type if remote_type in (
            "undefined", "string", "object", "boolean", "number", "function", "symbol", "bigint",
        ) else "unknown",
    }
    try:
        evaluated = page.request(
            "Runtime.evaluate", {"expression": _PAGE_READY_DIAGNOSTIC, "returnByValue": True},
        )
    except (AssertionError, OSError, ValueError, _DevToolsTransportError):
        return {**diagnostic, "snapshot": "unavailable"}
    if "exceptionDetails" in evaluated:
        return {**diagnostic, "snapshot": "javascript_exception"}
    result = evaluated.get("result")
    snapshot = result.get("value") if isinstance(result, dict) else None
    if not isinstance(snapshot, dict):
        return {**diagnostic, "snapshot": "unavailable"}
    diagnostic["snapshot"] = "available"
    for name, allowed in _READY_DIAGNOSTIC_VALUES.items():
        value = snapshot.get(name)
        diagnostic[name] = value if isinstance(value, str) and value in allowed else "unknown"
    for name in ("mainContent", "renderProbeStarted", "renderProbeResultReady", "domContentLoaded", "stylesReady", "imagesReady", "fontsReady"):
        value = snapshot.get(name)
        diagnostic[name] = value if isinstance(value, bool) else "unknown"
    return diagnostic


def _evaluate_script(page: _WebSocket, expression: str) -> object:
    evaluated = page.request("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    # CDP script exceptions are not transport failures. Keep locations, never browser text/URLs.
    if "exceptionDetails" in evaluated:
        details = evaluated["exceptionDetails"]
        assert isinstance(details, dict)
        raise AssertionError("layout probe raised a JavaScript exception "
            f"(zero-based line={details.get('lineNumber')}, column={details.get('columnNumber')})")
    return evaluated.get("result", {})


def _wait_for_document(page: _WebSocket, navigation: dict[str, object]) -> None:
    # Page.navigate starts navigation; its return does not establish a loaded document.
    # Redirects are allowed, but the original about:blank page is never readiness evidence.
    expression = 'document.readyState === "complete" && location.href !== "about:blank"'
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        result = _evaluate_script(page, expression)
        if isinstance(result, dict) and result.get("value") is True:
            return
        time.sleep(0.05)
    diagnostic = _layout_timeout_diagnostic(page, navigation, None)
    raise AssertionError("document did not become ready; " + json.dumps(diagnostic, sort_keys=True))


def _evaluate_page_once(
    edge: str,
    *,
    profile: Path,
    url: str,
    width: int,
    height: int,
    expression: str,
) -> object:
    profile.mkdir(parents=True)
    process = subprocess.Popen(
        [
            edge,
            "--headless=new",
            "--disable-background-networking",
            "--disable-gpu",
            "--no-first-run",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    page: _WebSocket | None = None
    browser_endpoint: str | None = None
    try:
        port, browser_path = _wait_for_devtools(profile, process)
        browser_endpoint = f"ws://127.0.0.1:{port}{browser_path}"
        page = _WebSocket(_page_websocket(port))
        page.request(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        navigation = page.request("Page.navigate", {"url": url})
        _wait_for_document(page, navigation)
        deadline = time.monotonic() + 10.0
        remote: object = None
        while time.monotonic() < deadline:
            remote = _evaluate_script(page, expression)
            if isinstance(remote, dict) and remote.get("type") != "undefined":
                return remote.get("value")
            time.sleep(0.05)
        diagnostic = _layout_timeout_diagnostic(page, navigation, remote)
        raise AssertionError(
            "layout probe did not become available; " + json.dumps(diagnostic, sort_keys=True),
        )
    finally:
        _stop_edge(process, page=page, browser_endpoint=browser_endpoint)


def evaluate_page(
    edge: str,
    *,
    profile: Path,
    prepare_url: Callable[[int], str],
    width: int,
    height: int,
    expression: str,
) -> object:
    failures: list[BaseException] = []
    for attempt in range(1, _EVALUATE_PAGE_ATTEMPTS + 1):
        url = prepare_url(attempt)
        try:
            return _evaluate_page_once(
                edge,
                profile=profile / f"attempt-{attempt}",
                url=url,
                width=width,
                height=height,
                expression=expression,
            )
        except (OSError, _DevToolsTransportError) as exc:
            failures.append(exc)
    last_failure = failures[-1]
    raise _DevToolsTransportError(
        "Edge DevTools transport failed after "
        f"{_EVALUATE_PAGE_ATTEMPTS} fresh sessions: "
        f"{type(last_failure).__name__}: {last_failure}",
    ) from last_failure


def app_window_snapshot(process_id: int, marker: str) -> dict[str, object]:
    """Independently observe native windows; return only counts and fixed probe stages."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    result: dict[str, object] = {"ownedVisible": 0, "otherProbeVisible": 0, "stages": []}
    stages: list[str] = []

    @callback_type
    def observe(handle, _context):
        if not user32.IsWindowVisible(handle):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(handle, title, len(title))
        if owner.value == process_id:
            result["ownedVisible"] += 1
        for stage in ("loaded", "closing", "returned", "stalled"):
            if title.value.startswith(f"{marker} {stage}"):
                stages.append(stage)
                if owner.value != process_id:
                    result["otherProbeVisible"] += 1
                break
        return True

    if not user32.EnumWindows(observe, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    result["stages"] = sorted(stages)
    return result


def wait_for_app_window_close(edge: str, *, profile: Path, url: str) -> None:
    """Verify that a real Edge app target closes itself after rendering the page."""
    profile.mkdir(parents=True)
    process = subprocess.Popen(
        [
            edge,
            "--disable-background-mode",
            "--disable-background-networking",
            "--no-first-run",
            "--remote-allow-origins=*",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            f"--app={url}",
            "--window-size=820,660",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    browser_endpoint: str | None = None
    try:
        port, browser_path = _wait_for_devtools(profile, process)
        browser_endpoint = f"ws://127.0.0.1:{port}{browser_path}"
        saw_target = False
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                targets = _devtools_targets(port)
            except (OSError, ValueError):
                if saw_target and process.poll() is not None:
                    return
                time.sleep(0.05)
                continue
            target_open = any(
                target.get("type") == "page" and target.get("url") == url for target in targets
            )
            saw_target = saw_target or target_open
            if saw_target and not target_open:
                return
            time.sleep(0.05)
        raise AssertionError("Edge app window did not close after Manager maintenance state")
    finally:
        _stop_edge(process, page=None, browser_endpoint=browser_endpoint)
