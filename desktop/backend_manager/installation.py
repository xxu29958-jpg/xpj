"""Discovery of an installed Ticketbox instance from the installer registry key."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend_manager.version_contract import is_managed_release_version

_REGISTRY_PATH = r"Software\Ticketbox"
_REGISTRY_VALUE_NAMES = (
    "InstallDir",
    "DataRoot",
    "BackendPort",
    "PgPort",
    "BackendServiceName",
    "PgServiceName",
    "BackendVersion",
)
_SERVICE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_OWNER_RECOVERY_CHANNEL_PATTERN = re.compile(r"managed_host\Z")
_RELEASE_CONFIG_SCHEMA = "ticketbox-windows-release-v1"
_MAX_RELEASE_CONFIG_BYTES = 64 * 1024
_INSTALLATION_ID_NAMESPACE = b"ticketbox-installation-v1\0"


class InstallationConfigError(RuntimeError):
    """Raised when the installer registry key exists but is incomplete or invalid."""

    def __init__(self, message: str, *, code: str = "installation_config_invalid") -> None:
        super().__init__(message)
        self.code = code


def installation_id_for_app_data(app_data_dir: Path) -> str:
    canonical = os.path.normcase(str(app_data_dir.resolve())).encode("utf-8")
    digest = hashlib.sha256(_INSTALLATION_ID_NAMESPACE + canonical).hexdigest()
    return f"ticketbox-{digest[:32]}"


@dataclass(frozen=True)
class InstalledLayout:
    """Paths and ports written by ``ticketbox-installer.iss``."""

    install_dir: Path
    data_root: Path
    backend_port: int
    pg_port: int
    backend_service_name: str
    pg_service_name: str
    backend_version: str

    @property
    def app_data_dir(self) -> Path:
        return self.data_root / "app"

    @property
    def release_config_path(self) -> Path:
        return self.install_dir / "installer" / "windows-release-config.json"

    @property
    def manager_executable_path(self) -> Path:
        return self.install_dir / "manager" / "ticketbox-manager.exe"

    @property
    def installation_id(self) -> str:
        return installation_id_for_app_data(self.app_data_dir)


@dataclass(frozen=True)
class WindowsReleaseConfig:
    backend_service_name: str
    pg_service_name: str
    service_state_timeout_ms: int
    service_poll_interval_ms: int
    postgres_ready_timeout_ms: int
    backend_ready_timeout_ms: int
    backend_ready_poll_interval_ms: int
    backend_health_request_timeout_ms: int

    @property
    def service_state_timeout_seconds(self) -> float:
        return self.service_state_timeout_ms / 1000.0

    @property
    def service_poll_seconds(self) -> float:
        return self.service_poll_interval_ms / 1000.0

    @property
    def postgres_ready_timeout_seconds(self) -> float:
        return self.postgres_ready_timeout_ms / 1000.0

    @property
    def backend_ready_timeout_seconds(self) -> float:
        return self.backend_ready_timeout_ms / 1000.0

    @property
    def backend_ready_poll_seconds(self) -> float:
        return self.backend_ready_poll_interval_ms / 1000.0

    @property
    def backend_health_request_timeout_seconds(self) -> float:
        return self.backend_health_request_timeout_ms / 1000.0

    @property
    def process_boundary_margin_seconds(self) -> float:
        return max(
            self.backend_health_request_timeout_seconds,
            self.service_poll_seconds * 2,
            1.0,
        )

    @property
    def service_validation_timeout_seconds(self) -> float:
        return self.service_state_timeout_seconds + self.process_boundary_margin_seconds

    def helper_action_phase_budget_seconds(self, action: str) -> dict[str, float]:
        service = self.service_state_timeout_seconds
        postgres = max(service, self.postgres_ready_timeout_seconds)
        process_margin = self.process_boundary_margin_seconds
        if action not in {"start", "stop", "restart"}:
            raise InstallationConfigError(f"不支持的服务操作：{action}")

        phases = {
            "pre_action_contract_validation": service + process_margin,
        }
        if action in {"stop", "restart"}:
            phases.update(
                {
                    "backend_settle_before_stop": service,
                    "backend_stop": service,
                    "post_stop_runtime_validation": service + process_margin,
                },
            )
        if action in {"start", "restart"}:
            phases.update(
                {
                    "postgres_settle_before_start": postgres,
                    "postgres_start": postgres,
                    "backend_settle_before_start": service,
                    "backend_start": service,
                    "backend_readiness": (
                        self.backend_ready_timeout_seconds
                        + self.backend_health_request_timeout_seconds
                    ),
                },
            )
        phases["watchdog_scheduler_margin"] = process_margin
        return phases

    def helper_watchdog_seconds(self, action: str) -> float:
        return sum(self.helper_action_phase_budget_seconds(action).values())

    def helper_parent_timeout_ms(self, action: str) -> int:
        result_channel_flush = self.process_boundary_margin_seconds
        return math.ceil((self.helper_watchdog_seconds(action) + result_channel_flush) * 1000)


def _parse_port(raw: str, name: str) -> int:
    try:
        port = int(raw)
    except ValueError as exc:
        raise InstallationConfigError(f"安装信息里的 {name} 不是有效端口：{raw!r}") from exc
    if not 1 <= port <= 65535:
        raise InstallationConfigError(f"安装信息里的 {name} 超出有效范围：{port}")
    return port


def _parse_service_name(raw: str, name: str) -> str:
    value = raw.strip()
    if not _SERVICE_NAME_PATTERN.fullmatch(value):
        raise InstallationConfigError(f"安装信息里的 {name} 不是受支持的服务名：{raw!r}")
    return value


def _parse_backend_version(raw: str) -> str:
    value = raw.strip()
    if not is_managed_release_version(value):
        raise InstallationConfigError(f"安装信息里的 BackendVersion 不是受支持的版本：{raw!r}")
    return value


def _config_text(config: Mapping[str, object], name: str, pattern: re.Pattern[str]) -> str:
    value = config.get(name)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InstallationConfigError(f"Windows release config 的 {name} 格式无效。")
    return value


def _config_integer(
    config: Mapping[str, object],
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    value = config.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise InstallationConfigError(
            f"Windows release config 的 {name} 必须是 {minimum}..{maximum} 整数。",
        )
    return value


def parse_windows_release_config(config: Mapping[str, object]) -> WindowsReleaseConfig:
    if config.get("schema") != _RELEASE_CONFIG_SCHEMA:
        raise InstallationConfigError(f"Windows release config schema 不受支持：{config.get('schema')}")
    service_pattern = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
    backend_service_name = _config_text(config, "backend_service_name", service_pattern)
    pg_service_name = _config_text(config, "pg_service_name", service_pattern)
    _config_text(config, "owner_recovery_channel", _OWNER_RECOVERY_CHANNEL_PATTERN)
    service_timeout = _config_integer(config, "service_state_timeout_ms", 1000, 300000)
    service_poll = _config_integer(config, "service_poll_interval_ms", 10, 10000)
    postgres_timeout = _config_integer(config, "postgres_ready_timeout_ms", 1000, 300000)
    backend_timeout = _config_integer(config, "backend_ready_timeout_ms", 1000, 300000)
    backend_poll = _config_integer(config, "backend_ready_poll_interval_ms", 10, 10000)
    health_timeout = _config_integer(config, "backend_health_request_timeout_ms", 1000, 300000)
    if service_poll > service_timeout or backend_poll > backend_timeout or health_timeout > backend_timeout:
        raise InstallationConfigError("Windows release config 的轮询或请求超时不能大于对应就绪超时。")
    return WindowsReleaseConfig(
        backend_service_name=backend_service_name,
        pg_service_name=pg_service_name,
        service_state_timeout_ms=service_timeout,
        service_poll_interval_ms=service_poll,
        postgres_ready_timeout_ms=postgres_timeout,
        backend_ready_timeout_ms=backend_timeout,
        backend_ready_poll_interval_ms=backend_poll,
        backend_health_request_timeout_ms=health_timeout,
    )


def load_installed_release_config(layout: InstalledLayout) -> WindowsReleaseConfig:
    try:
        return _load_installed_release_config(layout)
    except InstallationConfigError as exc:
        raise InstallationConfigError(str(exc), code="release_contract_invalid") from exc


def _load_installed_release_config(layout: InstalledLayout) -> WindowsReleaseConfig:
    path = layout.release_config_path
    try:
        if not path.is_file() or path.stat().st_size > _MAX_RELEASE_CONFIG_BYTES:
            raise InstallationConfigError(f"缺少或拒绝过大的 Windows release config：{path}")
        decoded = json.loads(path.read_text(encoding="utf-8-sig"))
    except InstallationConfigError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationConfigError(f"无法读取 Windows release config：{path}") from exc
    if not isinstance(decoded, dict):
        raise InstallationConfigError("Windows release config 顶层必须是 JSON object。")
    release = parse_windows_release_config(decoded)
    if release.backend_service_name.casefold() != layout.backend_service_name.casefold():
        raise InstallationConfigError("安装注册表与 Windows release config 的后端服务身份不一致。")
    if release.pg_service_name.casefold() != layout.pg_service_name.casefold():
        raise InstallationConfigError("安装注册表与 Windows release config 的 PostgreSQL 服务身份不一致。")
    return release


def parse_installed_layout(values: Mapping[str, str]) -> InstalledLayout:
    """Validate registry values before they become runtime configuration."""
    missing = [name for name in _REGISTRY_VALUE_NAMES if not values.get(name, "").strip()]
    if missing:
        raise InstallationConfigError(f"安装信息不完整，缺少：{', '.join(missing)}")
    return InstalledLayout(
        install_dir=Path(values["InstallDir"]).resolve(),
        data_root=Path(values["DataRoot"]).resolve(),
        backend_port=_parse_port(values["BackendPort"], "BackendPort"),
        pg_port=_parse_port(values["PgPort"], "PgPort"),
        backend_service_name=_parse_service_name(values["BackendServiceName"], "BackendServiceName"),
        pg_service_name=_parse_service_name(values["PgServiceName"], "PgServiceName"),
        backend_version=_parse_backend_version(values["BackendVersion"]),
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
        for name in _REGISTRY_VALUE_NAMES:
            try:
                values[name] = str(winreg.QueryValueEx(key, name)[0])
            except FileNotFoundError:
                values[name] = ""
            except OSError as exc:
                raise InstallationConfigError(f"无法读取 Windows 安装信息 {name}：{exc}") from exc
    return values


def discover_installed_layout() -> InstalledLayout | None:
    """Return the installed layout, or ``None`` when Ticketbox is not installed."""
    try:
        values = _read_registry_values()
        return parse_installed_layout(values) if values is not None else None
    except InstallationConfigError as exc:
        raise InstallationConfigError(str(exc), code="registry_contract_invalid") from exc


def _windows_powershell_path() -> Path:
    if os.name != "nt":
        raise InstallationConfigError("正式安装服务契约校验只支持 Windows。")
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    kernel32.GetWindowsDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel32.GetWindowsDirectoryW.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetWindowsDirectoryW(buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        raise InstallationConfigError("无法定位受信任的 Windows PowerShell。")
    executable = Path(buffer.value) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not executable.is_file():
        raise InstallationConfigError(f"受信任的 Windows PowerShell 不存在：{executable}")
    return executable


def _run_installed_lifecycle_validation(
    layout: InstalledLayout,
    release: WindowsReleaseConfig,
    mode_switch: str,
) -> None:
    script = layout.install_dir / "installer" / "install_bundled_services.ps1"
    if not script.is_file():
        raise InstallationConfigError(f"缺少安装服务契约脚本：{script}")
    command = [
        str(_windows_powershell_path()),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-InstallDir",
        str(layout.install_dir),
        "-DataRoot",
        str(layout.data_root),
        "-PgPort",
        str(layout.pg_port),
        "-BackendPort",
        str(layout.backend_port),
        "-TargetBackendVersion",
        layout.backend_version,
        "-ExpectedBackendServiceName",
        layout.backend_service_name,
        "-ExpectedPgServiceName",
        layout.pg_service_name,
        mode_switch,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=release.service_validation_timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallationConfigError(
            f"无法完成 Windows 服务归属校验：{exc}",
            code="service_contract_invalid",
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "无诊断输出").strip()[-1200:]
        raise InstallationConfigError(
            f"Windows 服务归属校验失败：{detail}",
            code="service_contract_invalid",
        )


def validate_installed_service_contract(layout: InstalledLayout, release: WindowsReleaseConfig) -> None:
    """Ask the installed lifecycle owner to validate both SCM records exactly."""
    _run_installed_lifecycle_validation(layout, release, "-ValidateInstalledServicesOnly")


def validate_installed_backend_stopped(layout: InstalledLayout, release: WindowsReleaseConfig) -> None:
    """Prove the installed backend listener and runtime processes are gone."""
    _run_installed_lifecycle_validation(layout, release, "-ValidateBackendRuntimeStoppedOnly")
