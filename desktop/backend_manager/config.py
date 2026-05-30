"""Resolved manager configuration — read, never hardcoded.

Everything the manager needs (backend location, interpreter, bind host/port, the
public tunnel URL) is resolved at runtime from the SAME sources the backend uses:

* the backend ``.env`` (via ``python-dotenv``, exactly as ``app/config.py`` loads it)
  for ``PUBLIC_BASE_URL``;
* environment variables for every launcher-level knob, each with a documented
  default that matches the project convention (``scripts/start_backend.ps1`` binds
  ``127.0.0.1`` and defaults ``-Port 8000``);
* filesystem discovery for the backend root and its venv interpreter.

All URLs are derived from one host/port pair, so there is a single place to change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

# Env-var overrides (documented defaults match scripts/start_backend.ps1).
_ENV_BACKEND_ROOT = "TICKETBOX_BACKEND_ROOT"
_ENV_BACKEND_HOST = "TICKETBOX_BACKEND_HOST"
_ENV_BACKEND_PORT = "TICKETBOX_BACKEND_PORT"
_ENV_MANAGER_HOST = "TICKETBOX_MANAGER_HOST"
_ENV_MANAGER_PORT = "TICKETBOX_MANAGER_PORT"

_DEFAULT_BACKEND_HOST = "127.0.0.1"  # start_backend.ps1 binds loopback
_DEFAULT_BACKEND_PORT = 8000  # start_backend.ps1 `param([int]$Port = 8000)`
_DEFAULT_MANAGER_HOST = "127.0.0.1"
_DEFAULT_MANAGER_PORT = 8799


class ConfigError(RuntimeError):
    """Raised when a required path (backend root / venv interpreter) cannot be resolved."""


@dataclass(frozen=True)
class ManagerConfig:
    backend_root: Path
    venv_python: Path
    backend_host: str
    backend_port: int
    manager_host: str
    manager_port: int
    public_base_url: str | None

    @property
    def backend_origin(self) -> str:
        return f"http://{self.backend_host}:{self.backend_port}"

    @property
    def health_url(self) -> str:
        return f"{self.backend_origin}/api/health"

    @property
    def owner_url(self) -> str:
        return f"{self.backend_origin}/owner"

    @property
    def manager_url(self) -> str:
        return f"http://{self.manager_host}:{self.manager_port}/"


def _discover_backend_root() -> Path:
    override = os.getenv(_ENV_BACKEND_ROOT)
    if override:
        return Path(override).resolve()
    # desktop/backend_manager/config.py -> repo root is two levels up.
    return (Path(__file__).resolve().parents[2] / "backend").resolve()


def _discover_venv_python(backend_root: Path) -> Path:
    # Windows venv layout; the backend is created with `uv venv` at backend/.venv.
    candidate = backend_root / ".venv" / "Scripts" / "python.exe"
    if not candidate.exists():
        raise ConfigError(f"backend venv interpreter not found at {candidate}")
    return candidate


def _env_port(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a valid port") from exc


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _require_loopback_manager_host(host: str) -> str:
    """The control surface serves a bearer token and accepts start/stop/restart
    POSTs, so it MUST stay loopback-only. Binding to ``0.0.0.0`` or a LAN IP
    would let any reachable client GET ``/`` to read the token and then POST
    control actions. Refuse a non-loopback host before startup."""
    if host.strip().lower() in _LOOPBACK_HOSTS or host.strip().startswith("127."):
        return host
    raise ConfigError(
        f"{_ENV_MANAGER_HOST}={host!r} must be loopback (127.0.0.1 / ::1 / localhost): "
        "the manager control surface serves a control token and must not bind to a public or LAN address.",
    )


def load_config() -> ManagerConfig:
    """Resolve the manager configuration from env + the backend ``.env`` + discovery."""
    backend_root = _discover_backend_root()
    if not backend_root.exists():
        raise ConfigError(f"backend root not found at {backend_root}")
    env_values = dotenv_values(backend_root / ".env")
    public = (env_values.get("PUBLIC_BASE_URL") or "").strip() or None
    return ManagerConfig(
        backend_root=backend_root,
        venv_python=_discover_venv_python(backend_root),
        backend_host=os.getenv(_ENV_BACKEND_HOST, _DEFAULT_BACKEND_HOST),
        backend_port=_env_port(_ENV_BACKEND_PORT, _DEFAULT_BACKEND_PORT),
        manager_host=_require_loopback_manager_host(os.getenv(_ENV_MANAGER_HOST, _DEFAULT_MANAGER_HOST)),
        manager_port=_env_port(_ENV_MANAGER_PORT, _DEFAULT_MANAGER_PORT),
        public_base_url=public,
    )
