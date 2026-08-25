"""Discover the one installed Ticketbox instance from ``installation.json``."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend_manager.version_contract import is_managed_release_version

_REGISTRY_PATH = r"Software\Ticketbox"
_SERVICE_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_INSTALLATION_ID_NAMESPACE = b"ticketbox-installation-v1\0"
_INSTALLATION_BINDING_SCHEMA = "ticketbox-installed-instance-v1"
_VNEXT_RELEASE_DEFAULTS = {
    "service_state_timeout_ms": 60_000,
    "service_poll_interval_ms": 250,
    "postgres_ready_timeout_ms": 90_000,
    "backend_ready_timeout_ms": 120_000,
    "backend_ready_poll_interval_ms": 1_000,
    "backend_health_request_timeout_ms": 2_000,
    "database_tool_timeout_ms": 600_000,
    "dataset_backup_helper_timeout_ms": 1_800_000,
    "dataset_restore_helper_timeout_ms": 3_600_000,
    "dataset_payload_verification_timeout_ms": 1_800_000,
    "complete_dataset_cleanup_reserve_ms": 3_600_000,
    "complete_dataset_backup_timeout_ms": 5_400_000,
    "complete_dataset_restore_timeout_ms": 57_600_000,
}


class InstallationConfigError(RuntimeError):
    """Raised when the installed-instance binding is incomplete or invalid."""

    def __init__(self, message: str, *, code: str = "installation_config_invalid") -> None:
        super().__init__(message)
        self.code = code


def installation_id_for_app_data(app_data_dir: Path) -> str:
    canonical = os.path.normcase(str(app_data_dir.resolve())).encode("utf-8")
    digest = hashlib.sha256(_INSTALLATION_ID_NAMESPACE + canonical).hexdigest()
    return f"ticketbox-{digest[:32]}"


@dataclass(frozen=True)
class InstalledLayout:
    """Runtime layout bound by ``installation.json`` and its InstallDir locator."""

    install_dir: Path
    data_root: Path
    backend_port: int
    pg_port: int
    backend_service_name: str
    pg_service_name: str
    backend_version: str
    install_id: str

    @property
    def app_data_dir(self) -> Path:
        return self.data_root / "app"

    @property
    def installation_id(self) -> str:
        return self.install_id


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
    database_tool_timeout_ms: int
    dataset_backup_helper_timeout_ms: int
    dataset_restore_helper_timeout_ms: int
    dataset_payload_verification_timeout_ms: int
    complete_dataset_cleanup_reserve_ms: int
    complete_dataset_backup_timeout_ms: int
    complete_dataset_restore_timeout_ms: int

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

    def complete_dataset_action_timeout_seconds(self, action: str) -> float:
        if action == "backup":
            return self.complete_dataset_backup_timeout_ms / 1000.0
        if action == "restore":
            return self.complete_dataset_restore_timeout_ms / 1000.0
        raise InstallationConfigError(f"操作没有完整数据集预算：{action}")

    def powershell_action_timeout_seconds(self, action: str) -> float:
        process_deadline = (
            self.complete_dataset_action_timeout_seconds(action)
            + self.complete_dataset_cleanup_reserve_ms / 1000.0
        )
        return process_deadline + self.process_boundary_margin_seconds

    def helper_action_phase_budget_seconds(self, action: str) -> dict[str, float]:
        service = self.service_state_timeout_seconds
        postgres = max(service, self.postgres_ready_timeout_seconds)
        process_margin = self.process_boundary_margin_seconds
        if action not in {"start", "stop", "restart", "backup", "restore", "inventory"}:
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
        if action == "backup":
            phases.update(
                {
                    "complete_dataset_backup_owner": self.powershell_action_timeout_seconds(action),
                },
            )
        if action == "restore":
            phases.update(
                {
                    "complete_dataset_restore_owner": self.powershell_action_timeout_seconds(action),
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
                        self.backend_ready_timeout_seconds + self.backend_health_request_timeout_seconds
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


def load_installed_release_config(layout: InstalledLayout) -> WindowsReleaseConfig:
    return WindowsReleaseConfig(
        backend_service_name=layout.backend_service_name,
        pg_service_name=layout.pg_service_name,
        **_VNEXT_RELEASE_DEFAULTS,
    )


def _read_install_dir() -> str | None:
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

    with key:
        try:
            value = str(winreg.QueryValueEx(key, "InstallDir")[0]).strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise InstallationConfigError(f"无法读取 Windows 安装位置：{exc}") from exc
    return value or None


def parse_installed_binding(
    payload: Mapping[str, object],
    install_dir: str | None,
) -> InstalledLayout:
    if not install_dir:
        raise InstallationConfigError("installation.json 存在，但缺少 InstallDir 定位。")
    required = (
        "install_id",
        "data_root",
        "active_release_id",
        "pg_service_name",
        "backend_service_name",
        "pg_port",
        "backend_port",
    )
    missing = [name for name in required if payload.get(name) in (None, "")]
    if missing:
        raise InstallationConfigError(f"installation.json 不完整，缺少：{', '.join(missing)}")
    if payload.get("schema") != _INSTALLATION_BINDING_SCHEMA:
        raise InstallationConfigError("installation.json schema 不是 ticketbox-installed-instance-v1")
    raw_install_id = str(payload["install_id"]).strip().lower()
    try:
        install_id = str(uuid.UUID(raw_install_id))
    except ValueError as exc:
        raise InstallationConfigError("installation.json install_id 不是 canonical UUID。") from exc
    if install_id != raw_install_id:
        raise InstallationConfigError("installation.json install_id 不是 canonical UUID。")
    return InstalledLayout(
        install_dir=Path(install_dir).resolve(),
        data_root=Path(str(payload["data_root"])).resolve(),
        backend_port=_parse_port(str(payload["backend_port"]), "backend_port"),
        pg_port=_parse_port(str(payload["pg_port"]), "pg_port"),
        backend_service_name=_parse_service_name(str(payload["backend_service_name"]), "backend_service_name"),
        pg_service_name=_parse_service_name(str(payload["pg_service_name"]), "pg_service_name"),
        backend_version=_parse_backend_version(str(payload["active_release_id"])),
        install_id=install_id,
    )


def _installation_binding_path() -> Path:
    program_data = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    return program_data / "Ticketbox" / "machine" / "installation.json"


def _read_installation_binding() -> dict[str, object] | None:
    path = _installation_binding_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallationConfigError(f"无法读取 installation.json：{path}") from exc
    if not isinstance(payload, dict):
        raise InstallationConfigError("installation.json 顶层必须是 JSON object。")
    return payload


def discover_installed_layout() -> InstalledLayout | None:
    """Return the installed layout, or ``None`` when Ticketbox is not installed."""
    try:
        binding = _read_installation_binding()
        if binding is None:
            return None
        return parse_installed_binding(binding, _read_install_dir())
    except InstallationConfigError as exc:
        raise InstallationConfigError(str(exc), code="installed_binding_invalid") from exc


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
