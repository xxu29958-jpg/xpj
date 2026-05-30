"""Entry point — resolves config, wires the supervisor + control server + UI, runs until quit.

No import-time side effects: everything is constructed inside [main], and every value
comes from [load_config] (env / backend .env / discovery), never a hardcoded literal.

Run:  backend/.venv/Scripts/python.exe -m backend_manager   (cwd = desktop/)
"""

from __future__ import annotations

import contextlib
import secrets
import shutil
import subprocess
import threading
import time
from functools import partial
from pathlib import Path

from backend_manager.config import ManagerConfig, load_config
from backend_manager.control_server import ControlServer
from backend_manager.netinfo import lan_ip
from backend_manager.process import (
    health_ok,
    kill_listeners_on_port,
    spawn_backend,
    tree_kill,
)
from backend_manager.supervisor import BackendSupervisor

_CREATE_NO_WINDOW = 0x08000000
_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_UI_HTML = Path(__file__).resolve().parent / "ui.html"


def _open_in_browser(url: str) -> None:
    with contextlib.suppress(OSError):
        subprocess.Popen(["cmd", "/c", "start", "", url], creationflags=_CREATE_NO_WINDOW)


def _open_app_window(url: str) -> None:
    """Open the UI as a chromeless Edge ``--app`` window, falling back to the default browser."""
    edge = next((c for c in (*_EDGE_CANDIDATES, shutil.which("msedge")) if c and Path(c).exists()), None)
    if edge is None:
        _open_in_browser(url)
        return
    try:
        subprocess.Popen([edge, f"--app={url}", "--window-size=820,660"], creationflags=_CREATE_NO_WINDOW)
    except OSError:
        _open_in_browser(url)


class AppController:
    """Adapts the supervisor + resolved config into the dict the control server serves."""

    def __init__(self, supervisor: BackendSupervisor, config: ManagerConfig) -> None:
        self._sup = supervisor
        self._config = config

    def status(self) -> dict:
        snapshot = self._sup.status()
        ip = lan_ip()
        port = self._config.backend_port
        return {
            "running": snapshot.running,
            "health": snapshot.healthy,
            "uptime_seconds": snapshot.uptime_seconds,
            "pid": snapshot.pid,
            "port": port,
            "auto_restart": snapshot.auto_restart,
            "restarts": snapshot.restarts,
            "lan": f"{ip}:{port}" if ip else "未发现局域网地址",
            "tunnel": self._config.public_base_url,
            "owner_url": self._config.owner_url,
            "log": snapshot.log,
        }

    def start(self) -> None:
        self._sup.start()

    def stop(self) -> None:
        self._sup.stop()

    def restart(self) -> None:
        self._sup.restart()

    def auto_restart(self) -> None:
        self._sup.toggle_auto_restart()

    def open_console(self) -> None:
        _open_in_browser(self._config.owner_url)


def _build_supervisor(config: ManagerConfig) -> BackendSupervisor:
    return BackendSupervisor(
        spawn=partial(
            spawn_backend,
            backend_root=config.backend_root,
            venv_python=config.venv_python,
            host=config.backend_host,
            port=config.backend_port,
        ),
        tree_kill=tree_kill,
        kill_port=partial(kill_listeners_on_port, config.backend_port),
        health=partial(health_ok, config.health_url),
    )


def main() -> None:
    config = load_config()
    supervisor = _build_supervisor(config)
    supervisor.start()

    stop_event = threading.Event()
    threading.Thread(target=supervisor.run_monitor, args=(stop_event,), daemon=True).start()

    token = secrets.token_urlsafe(24)
    server = ControlServer(
        config.manager_host,
        config.manager_port,
        controller=AppController(supervisor, config),
        token=token,
        ui_html=_UI_HTML,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()

    _open_app_window(config.manager_url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        server.shutdown()


if __name__ == "__main__":
    main()
