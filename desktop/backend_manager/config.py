"""Resolve Desktop Manager configuration for source and installed runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dotenv import dotenv_values

from backend_manager.installation import InstallationConfigError, InstalledLayout, discover_installed_layout

_ENV_BACKEND_ROOT = "TICKETBOX_BACKEND_ROOT"
_ENV_BACKEND_HOST = "TICKETBOX_BACKEND_HOST"
_ENV_BACKEND_PORT = "TICKETBOX_BACKEND_PORT"
_ENV_MANAGER_HOST = "TICKETBOX_MANAGER_HOST"
_ENV_MANAGER_PORT = "TICKETBOX_MANAGER_PORT"
_ENV_MANAGER_MODE = "TICKETBOX_MANAGER_MODE"

_DEFAULT_BACKEND_HOST = "127.0.0.1"
_DEFAULT_BACKEND_PORT = 8000
_DEFAULT_MANAGER_HOST = "127.0.0.1"
_DEFAULT_MANAGER_PORT = 8799
_BACKEND_SERVICE_NAME = "TicketboxBackend"
_PG_SERVICE_NAME = "TicketboxPg"


class ConfigError(RuntimeError):
    """Raised when the manager cannot resolve a usable runtime configuration."""


@dataclass(frozen=True)
class SourceRuntimeConfig:
    backend_root: Path
    venv_python: Path

    @property
    def env_path(self) -> Path:
        return self.backend_root / ".env"


@dataclass(frozen=True)
class InstalledRuntimeConfig:
    layout: InstalledLayout
    backend_service_name: str = _BACKEND_SERVICE_NAME
    pg_service_name: str = _PG_SERVICE_NAME

    @property
    def env_path(self) -> Path:
        return self.layout.env_path

    @property
    def log_path(self) -> Path:
        return self.layout.log_path


RuntimeConfig = SourceRuntimeConfig | InstalledRuntimeConfig


@dataclass(frozen=True)
class ManagerConfig:
    runtime: RuntimeConfig
    backend_host: str
    backend_port: int
    manager_host: str
    manager_port: int
    public_base_url: str | None

    @property
    def runtime_mode(self) -> Literal["source", "installed"]:
        return "installed" if isinstance(self.runtime, InstalledRuntimeConfig) else "source"

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
    return (Path(__file__).resolve().parents[2] / "backend").resolve()


def _discover_source_runtime() -> SourceRuntimeConfig:
    backend_root = _discover_backend_root()
    if not backend_root.exists():
        raise ConfigError(f"backend root not found at {backend_root}")
    venv_python = backend_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        raise ConfigError(f"backend venv interpreter not found at {venv_python}")
    return SourceRuntimeConfig(backend_root=backend_root, venv_python=venv_python)


def _env_port(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        port = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not a valid port") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"{name}={raw!r} is outside 1..65535")
    return port


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _require_loopback_manager_host(host: str) -> str:
    """Refuse a public control surface that would expose the per-process token."""
    if host.strip().lower() in _LOOPBACK_HOSTS or host.strip().startswith("127."):
        return host
    raise ConfigError(
        f"{_ENV_MANAGER_HOST}={host!r} must be loopback (127.0.0.1 / ::1 / localhost): "
        "the manager control surface serves a control token and must not bind to a public or LAN address.",
    )


def _manager_mode() -> Literal["auto", "source", "installed"]:
    raw = os.getenv(_ENV_MANAGER_MODE, "auto").strip().lower()
    if raw not in {"auto", "source", "installed"}:
        raise ConfigError(f"{_ENV_MANAGER_MODE} must be auto, source, or installed; got {raw!r}")
    return cast(Literal["auto", "source", "installed"], raw)


def _resolve_runtime(mode_override: Literal["source", "installed"] | None = None) -> RuntimeConfig:
    mode = mode_override or _manager_mode()
    try:
        installed = discover_installed_layout() if mode != "source" else None
    except InstallationConfigError as exc:
        raise ConfigError(str(exc)) from exc

    if mode == "installed":
        if installed is None:
            raise ConfigError("未找到小票夹正式安装信息，请重新安装或改用 TICKETBOX_MANAGER_MODE=source。")
        return InstalledRuntimeConfig(installed)
    if mode == "auto" and installed is not None and not os.getenv(_ENV_BACKEND_ROOT):
        return InstalledRuntimeConfig(installed)
    return _discover_source_runtime()


def load_config(*, mode_override: Literal["source", "installed"] | None = None) -> ManagerConfig:
    """Resolve one runtime from installer registry or source-tree discovery."""
    runtime = _resolve_runtime(mode_override)
    try:
        env_values = dotenv_values(runtime.env_path)
    except OSError:
        env_values = {}
    public = (env_values.get("PUBLIC_BASE_URL") or "").strip() or None
    if isinstance(runtime, InstalledRuntimeConfig):
        backend_host = _DEFAULT_BACKEND_HOST
        backend_port = runtime.layout.backend_port
    else:
        backend_host = os.getenv(_ENV_BACKEND_HOST, _DEFAULT_BACKEND_HOST)
        backend_port = _env_port(_ENV_BACKEND_PORT, _DEFAULT_BACKEND_PORT)
    return ManagerConfig(
        runtime=runtime,
        backend_host=backend_host,
        backend_port=backend_port,
        manager_host=_require_loopback_manager_host(os.getenv(_ENV_MANAGER_HOST, _DEFAULT_MANAGER_HOST)),
        manager_port=_env_port(_ENV_MANAGER_PORT, _DEFAULT_MANAGER_PORT),
        public_base_url=public,
    )
