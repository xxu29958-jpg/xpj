"""Real OS process primitives injected into [BackendSupervisor].

Kept separate from the supervision logic so the latter stays unit-testable: these
functions actually touch the OS (spawn uvicorn, tree-kill, free a port, HTTP probe)
and are only exercised by the running app, not the unit tests.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
import urllib.request
from collections import deque
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000  # don't pop a console window for child processes
_LOG_LINES = 300


class UvicornProcess:
    """A spawned uvicorn process whose stdout/stderr is pumped into a ring buffer.

    Satisfies the ``ManagedProcess`` protocol the supervisor depends on.
    """

    def __init__(self, popen: subprocess.Popen[str]) -> None:
        self._popen = popen
        self._log: deque[str] = deque(maxlen=_LOG_LINES)
        self._lock = threading.Lock()
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def pid(self) -> int:
        return self._popen.pid

    def poll(self) -> int | None:
        return self._popen.poll()

    def recent_log(self) -> list[str]:
        with self._lock:
            return list(self._log)

    def _pump(self) -> None:
        stream = self._popen.stdout
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            if line:
                with self._lock:
                    self._log.append(line.rstrip())


def spawn_backend(*, backend_root: Path, venv_python: Path, host: str, port: int) -> UvicornProcess:
    """Launch ``uvicorn app.main:app`` from the backend's own venv."""
    popen = subprocess.Popen(
        [
            str(venv_python), "-m", "uvicorn", "app.main:app",
            "--host", host, "--port", str(port), "--no-access-log",
        ],
        cwd=str(backend_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
    )
    return UvicornProcess(popen)


def tree_kill(pid: int) -> None:
    """Force-kill a process AND its descendants (``/T``).

    uvicorn's worker is a child process; killing only the parent would orphan the
    worker (still bound to the port). ``taskkill /T`` takes down the whole tree, so a
    stop actually frees the port.
    """
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )


def kill_listeners_on_port(port: int) -> None:
    """Kill any process currently listening on ``port`` (clears strays before a fresh start)."""
    with contextlib.suppress(subprocess.SubprocessError, OSError):
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -State Listen "
                f"-ErrorAction SilentlyContinue | ForEach-Object "
                f"{{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}",
            ],
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
            check=False,
        )


def health_ok(url: str, *, timeout: float = 3.0) -> bool:
    """``True`` iff ``GET url`` returns HTTP 200."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed localhost URL
            return response.status == 200
    except (OSError, ValueError):
        return False
