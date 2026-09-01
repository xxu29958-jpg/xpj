"""Real-backend fixture + shared real-manager helpers for the Desktop BFF e2e."""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend_manager.app_controller import AppController
from backend_manager.config import ManagerConfig, SourceRuntimeConfig
from backend_manager.control_server import ControlServer
from backend_manager.product_identity import ProductSession
from backend_manager.product_recovery import RebindRecovery
from backend_manager.runtime import RuntimeStatus

_HELPER = Path(__file__).resolve().parent / "_real_backend_helper.py"
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RealBackend:
    origin: str
    port: int
    pairing_code: str
    app_token: str
    account_name: str
    owner_ledger_id: str
    other_ledger_id: str

    def fresh_pairing_code(self) -> str:
        """Mint one single-use pairing code (each e2e ceremony needs its own)."""
        request = urllib.request.Request(
            f"{self.origin}/api/ledgers/{self.owner_ledger_id}/devices/pairing-codes",
            data=b"{}",
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.app_token}",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
        if response.status != 201:
            raise RuntimeError(f"could not mint a fresh pairing code: {payload}")
        return str(payload["pairing_code"])


def _backend_python() -> str:
    override = os.environ.get("TICKETBOX_E2E_BACKEND_PYTHON")
    candidates = [
        override,
        _REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    pytest.skip(
        "backend venv interpreter not found; set TICKETBOX_E2E_BACKEND_PYTHON "
        "to a Python with the backend requirements installed",
    )
    raise AssertionError("unreachable")


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_health(origin: str, process: subprocess.Popen[str], timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"real backend helper exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"{origin}/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("real backend did not become healthy in time")


@pytest.fixture(scope="session")
def real_backend(tmp_path_factory: pytest.TempPathFactory):
    """One real backend on the dedicated smoke DB, seeded with one pairing code.

    Environment resolution lives in the helper (explicit env first, then the
    contract-local test cluster derivation); the fixture only needs a backend
    interpreter and the app config placeholders.
    """

    port = _free_port()
    scratch = tmp_path_factory.mktemp("real-backend-e2e")
    env = {
        **os.environ,
        "UPLOAD_TOKEN": "e2e-upload-token",
        "APP_TOKEN": "e2e-app-token",
        "ADMIN_TOKEN": "e2e-admin-token",
        "UPLOAD_DIR": str(scratch / "uploads"),
        "OCR_PROVIDER": "empty",
        "GENERATE_THUMBNAIL": "false",
        "XPJ_E2E_BACKEND_PORT": str(port),
        "XPJ_EXTRA_LOOPBACK_HOSTS": f"127.0.0.1:{port}",
    }
    process = subprocess.Popen(
        [_backend_python(), str(_HELPER)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT / "backend"),
        env=env,
    )
    seed: dict | None = None
    assert process.stdout is not None
    try:
        deadline = time.monotonic() + 120.0
        helper_log: list[str] = []
        while seed is None and time.monotonic() < deadline:
            line = process.stdout.readline()
            if line == "" and process.poll() is not None:
                raise RuntimeError(
                    "real backend helper exited before seeding "
                    f"(code {process.returncode}): {''.join(helper_log)[-2000:]}"
                )
            helper_log.append(line)
            if line.startswith("E2E_SEED "):
                seed = json.loads(line.removeprefix("E2E_SEED ").strip())
        if seed is None:
            raise RuntimeError("real backend helper did not report its seed in time")
        origin = f"http://127.0.0.1:{port}"
        _wait_for_health(origin, process)
        yield RealBackend(
            origin=origin,
            port=port,
            pairing_code=str(seed["pairing_code"]),
            app_token=str(seed["app_token"]),
            account_name=str(seed["account_name"]),
            owner_ledger_id=str(seed["owner_ledger_id"]),
            other_ledger_id=str(seed["other_ledger_id"]),
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


# ── Shared real-manager helpers ────────────────────────────────────────────

E2E_CONTROL_TOKEN = "desktop-e2e-control-token"
E2E_INSTANCE_SECRET = "desktop-e2e-instance-secret"
E2E_INSTALLATION_ID = "e2e-desktop-installation-id"
UI_HTML = Path(__file__).resolve().parents[1] / "backend_manager" / "ui.html"


class HealthyE2ERuntime:
    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            mode="source",
            running=True,
            healthy=True,
            pid=None,
            uptime_seconds=1,
            auto_restart=True,
            auto_restart_configurable=True,
            restarts=0,
            backend_service_state=None,
            database_service_state=None,
            log=["ready"],
            health_state="healthy",
            health_detail="identity verified",
            runtime_access_state="available",
            owner_state="configured",
        )


def e2e_manager_config(backend_port: int) -> ManagerConfig:
    return ManagerConfig(
        runtime=SourceRuntimeConfig(Path("backend"), Path("python.exe"), Path("backend")),
        backend_host="127.0.0.1",
        backend_port=backend_port,
        manager_host="127.0.0.1",
        manager_port=8799,
        public_base_url=None,
        expected_backend_version=None,
        expected_installation_id=E2E_INSTALLATION_ID,
        health_request_timeout_seconds=5.0,
    )


@dataclass
class CredentialStores:
    """In-memory stand-ins for the two WinCred slots.

    Live WinCred IO is covered by the product_identity/product_recovery unit
    tests; the e2e exercises the full protocol, not the OS keystore.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, ProductSession] = {}
        self.recoveries: dict[str, RebindRecovery] = {}

    def controller_kwargs(self) -> dict:
        return {
            "product_session_loader": self.sessions.get,
            "product_session_saver": self.sessions.__setitem__,
            "product_session_deleter": lambda key: self.sessions.pop(key, None),
            "product_recovery_loader": self.recoveries.get,
            "product_recovery_saver": self.recoveries.__setitem__,
            "product_recovery_deleter": lambda key: self.recoveries.pop(key, None),
        }


def make_controller(backend_port: int, stores: CredentialStores) -> AppController:
    return AppController(
        HealthyE2ERuntime(),
        e2e_manager_config(backend_port),
        **stores.controller_kwargs(),
    )


def make_manager(controller: AppController) -> ControlServer:
    return ControlServer(
        "127.0.0.1",
        0,
        controller=controller,
        token=E2E_CONTROL_TOKEN,
        instance_secret=E2E_INSTANCE_SECRET,
        ui_html=UI_HTML,
    )


def manager_post_json(port: int, path: str, payload: dict | None, *, origin: str) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else b""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {
        "X-Control-Token": E2E_CONTROL_TOKEN,
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection.request("POST", path, body=body, headers=headers)
    response = connection.getresponse()
    status = response.status
    data = json.loads(response.read())
    connection.close()
    return status, data


def manager_bootstrap_cookies(manager: ControlServer, material_path: Path) -> str:
    bootstrap_url = manager.prepare_web_bootstrap(material_path)
    assert E2E_INSTANCE_SECRET not in bootstrap_url
    document = material_path.read_text(encoding="utf-8")
    assert E2E_INSTANCE_SECRET not in document
    assert E2E_CONTROL_TOKEN not in document
    match = re.search(r'name="bootstrap_token" value="([^"]+)"', document)
    assert match is not None
    body = urllib.parse.urlencode({"bootstrap_token": match.group(1)}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", manager.server_address[1], timeout=5)
    connection.request(
        "POST",
        "/api/bootstrap",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = connection.getresponse()
    assert response.status == 200
    cookies = response.headers.get_all("Set-Cookie")
    response.read()
    connection.close()
    assert cookies is not None and len(cookies) == 3
    assert all("HttpOnly" in cookie for cookie in cookies)
    assert not material_path.exists()
    return "; ".join(cookie.partition(";")[0] for cookie in cookies)


def manager_get(manager: ControlServer, path: str, cookie: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", manager.server_address[1], timeout=10)
    connection.request("GET", path, headers={"Cookie": cookie})
    response = connection.getresponse()
    status = response.status
    body = response.read().decode("utf-8", errors="replace")
    connection.close()
    return status, body


@contextmanager
def serving(server) -> Iterator[None]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
