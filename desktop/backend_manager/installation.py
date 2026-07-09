"""Discovery of an installed Ticketbox instance from the installer registry key."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_REGISTRY_PATH = r"Software\Ticketbox"


class InstallationConfigError(RuntimeError):
    """Raised when the installer registry key exists but is incomplete or invalid."""


@dataclass(frozen=True)
class InstalledLayout:
    """Paths and ports written by ``ticketbox-installer.iss``."""

    install_dir: Path
    data_root: Path
    backend_port: int
    pg_port: int

    @property
    def app_data_dir(self) -> Path:
        return self.data_root / "app"

    @property
    def env_path(self) -> Path:
        return self.app_data_dir / ".env"

    @property
    def log_path(self) -> Path:
        return self.app_data_dir / "logs" / "backend.log"


def _parse_port(raw: str, name: str) -> int:
    try:
        port = int(raw)
    except ValueError as exc:
        raise InstallationConfigError(f"安装信息里的 {name} 不是有效端口：{raw!r}") from exc
    if not 1 <= port <= 65535:
        raise InstallationConfigError(f"安装信息里的 {name} 超出有效范围：{port}")
    return port


def parse_installed_layout(values: Mapping[str, str]) -> InstalledLayout:
    """Validate registry values before they become runtime configuration."""
    missing = [name for name in ("InstallDir", "DataRoot", "BackendPort", "PgPort") if not values.get(name, "").strip()]
    if missing:
        raise InstallationConfigError(f"安装信息不完整，缺少：{', '.join(missing)}")
    return InstalledLayout(
        install_dir=Path(values["InstallDir"]).resolve(),
        data_root=Path(values["DataRoot"]).resolve(),
        backend_port=_parse_port(values["BackendPort"], "BackendPort"),
        pg_port=_parse_port(values["PgPort"], "PgPort"),
    )


def _read_registry_values() -> dict[str, str] | None:
    if os.name != "nt":
        return None

    import winreg

    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _REGISTRY_PATH, 0, access)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallationConfigError(f"无法读取 Windows 安装信息：{exc}") from exc

    values: dict[str, str] = {}
    with key:
        for name in ("InstallDir", "DataRoot", "BackendPort", "PgPort"):
            try:
                values[name] = str(winreg.QueryValueEx(key, name)[0])
            except FileNotFoundError:
                values[name] = ""
            except OSError as exc:
                raise InstallationConfigError(f"无法读取 Windows 安装信息 {name}：{exc}") from exc
    return values


def discover_installed_layout() -> InstalledLayout | None:
    """Return the installed layout, or ``None`` when Ticketbox is not installed."""
    values = _read_registry_values()
    return parse_installed_layout(values) if values is not None else None
