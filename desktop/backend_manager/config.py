"""Resolve Desktop Manager configuration for source and installed runtimes."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dotenv import dotenv_values

from backend_manager.installation import (
    InstallationConfigError,
    InstalledLayout,
    WindowsReleaseConfig,
    discover_installed_layout,
    installation_id_for_app_data,
    load_installed_release_config,
)

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
_SOURCE_HEALTH_REQUEST_TIMEOUT_SECONDS = 3.0


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
    release: WindowsReleaseConfig

    @property
    def backend_service_name(self) -> str:
        return self.layout.backend_service_name

    @property
    def pg_service_name(self) -> str:
        return self.layout.pg_service_name

RuntimeConfig = SourceRuntimeConfig | InstalledRuntimeConfig


@dataclass(frozen=True)
class ManagerConfig:
    runtime: RuntimeConfig
    backend_host: str
    backend_port: int
    manager_host: str
    manager_port: int
    public_base_url: str | None
    expected_backend_version: str | None
    expected_installation_id: str
    health_request_timeout_seconds: float

    @property
    def runtime_mode(self) -> Literal["source", "installed"]:
        return "installed" if isinstance(self.runtime, InstalledRuntimeConfig) else "source"

    @property
    def backend_origin(self) -> str:
        return self._origin_for_host(self.backend_connect_host)

    @property
    def backend_connect_host(self) -> str:
        host = self.backend_host.strip()
        if host == "0.0.0.0" or self._is_loopback_host(host):
            return "127.0.0.1"
        return host

    @property
    def health_url(self) -> str:
        return f"{self.backend_origin}/api/health/installation"

    @property
    def owner_url(self) -> str:
        return f"{self.backend_origin}/owner"

    @property
    def manager_url(self) -> str:
        return self.manager_url_for_port(self.manager_port)

    def manager_url_for_port(self, port: int) -> str:
        return f"{self._origin_for_host(self.manager_host, port)}/"

    @property
    def public_endpoint_state(self) -> Literal["configured", "unconfigured", "protected_unknown"]:
        if isinstance(self.runtime, InstalledRuntimeConfig):
            return "protected_unknown"
        return "configured" if self.public_base_url else "unconfigured"

    def lan_endpoint(self, detected_lan_ip: str | None) -> str | None:
        host = self.backend_host.strip()
        if self._is_loopback_host(host):
            return None
        if host == "0.0.0.0":
            return f"{detected_lan_ip}:{self.backend_port}" if detected_lan_ip else None
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"{display_host}:{self.backend_port}"

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        normalized = host.strip().strip("[]").lower()
        if normalized == "localhost" or normalized.startswith("127."):
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    def _origin_for_host(self, host: str, port: int | None = None) -> str:
        host = host.strip()
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port or self.backend_port}"


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


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _require_source_backend_host(host: str) -> str:
    """Accept only bind shapes that have a fixed loopback management path."""
    normalized = host.strip().lower()
    try:
        loopback_v4 = (
            ipaddress.ip_address(normalized).version == 4
            and ipaddress.ip_address(normalized).is_loopback
        )
    except ValueError:
        loopback_v4 = False
    if normalized in {"0.0.0.0", "localhost"} or loopback_v4:
        return host
    raise ConfigError(
        f"{_ENV_BACKEND_HOST}={host!r} must be IPv4 loopback or 0.0.0.0; "
        "use 0.0.0.0 for LAN access so health and Owner Console stay on 127.0.0.1.",
    )


def _require_loopback_manager_host(host: str) -> str:
    """Refuse a public control surface that would expose the per-process token."""
    normalized = host.strip().lower()
    try:
        loopback_v4 = (
            ipaddress.ip_address(normalized).version == 4
            and ipaddress.ip_address(normalized).is_loopback
        )
    except ValueError:
        loopback_v4 = False
    if normalized == "localhost":
        return normalized
    if loopback_v4:
        return ipaddress.ip_address(normalized).compressed
    raise ConfigError(
        f"{_ENV_MANAGER_HOST}={host!r} must be IPv4 loopback (127.0.0.1 / localhost): "
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
        release = load_installed_release_config(installed) if installed is not None else None
    except InstallationConfigError as exc:
        raise ConfigError(str(exc)) from exc

    if mode == "installed":
        if installed is None:
            raise ConfigError("未找到小票夹正式安装信息，请重新安装或改用 TICKETBOX_MANAGER_MODE=source。")
        assert release is not None
        return InstalledRuntimeConfig(installed, release)
    if mode == "auto" and installed is not None:
        assert release is not None
        return InstalledRuntimeConfig(installed, release)
    return _discover_source_runtime()


def load_config(*, mode_override: Literal["source", "installed"] | None = None) -> ManagerConfig:
    """Resolve one runtime from installer registry or source-tree discovery."""
    runtime = _resolve_runtime(mode_override)
    if isinstance(runtime, InstalledRuntimeConfig):
        backend_host = _DEFAULT_BACKEND_HOST
        backend_port = runtime.layout.backend_port
        public = None
        expected_backend_version = runtime.layout.backend_version
        expected_installation_id = runtime.layout.installation_id
        health_request_timeout_seconds = runtime.release.backend_health_request_timeout_seconds
    else:
        try:
            env_values = dotenv_values(runtime.env_path)
        except OSError:
            env_values = {}
        public = (env_values.get("PUBLIC_BASE_URL") or "").strip() or None
        backend_host = _require_source_backend_host(
            os.getenv(_ENV_BACKEND_HOST, _DEFAULT_BACKEND_HOST),
        )
        backend_port = _env_port(_ENV_BACKEND_PORT, _DEFAULT_BACKEND_PORT)
        expected_backend_version = None
        source_data_root = Path(os.getenv("TICKETBOX_DATA_DIR", str(runtime.backend_root)))
        expected_installation_id = installation_id_for_app_data(source_data_root)
        health_request_timeout_seconds = _SOURCE_HEALTH_REQUEST_TIMEOUT_SECONDS
    return ManagerConfig(
        runtime=runtime,
        backend_host=backend_host,
        backend_port=backend_port,
        manager_host=_require_loopback_manager_host(os.getenv(_ENV_MANAGER_HOST, _DEFAULT_MANAGER_HOST)),
        manager_port=_env_port(_ENV_MANAGER_PORT, _DEFAULT_MANAGER_PORT),
        public_base_url=public,
        expected_backend_version=expected_backend_version,
        expected_installation_id=expected_installation_id,
        health_request_timeout_seconds=health_request_timeout_seconds,
    )
