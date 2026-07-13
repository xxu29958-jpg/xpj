"""Desktop Manager entry point for source and installed-service runtimes."""

from __future__ import annotations

import argparse
import threading
from functools import partial
from pathlib import Path

from backend_manager.build_identity import load_frozen_manager_identity
from backend_manager.config import (
    ConfigError,
    InstalledRuntimeConfig,
    load_config,
    load_maintenance_manager_config,
)
from backend_manager.elevation import (
    HELPER_EXIT_ACCESS,
    HELPER_EXIT_CONFIG,
    HELPER_EXIT_LIFECYCLE_BUSY,
    HELPER_EXIT_MISSING_SERVICE,
    HELPER_EXIT_NOT_ELEVATED,
    HELPER_EXIT_OS,
    HELPER_EXIT_TRANSITION,
    ServiceAction,
    is_process_elevated,
    start_helper_watchdog,
    validate_helper_result_channel,
    write_helper_result,
)
from backend_manager.installation import (
    InstallationConfigError,
    validate_installed_backend_stopped,
    validate_installed_service_contract,
)
from backend_manager.lifecycle_lock import LifecycleBusyError, hold_installer_lifecycle_lock
from backend_manager.manager_startup import run_manager
from backend_manager.runtime import (
    RuntimeControlError,
    ServiceAccessError,
    ServiceMissingError,
    ServiceTransitionError,
)
from backend_manager.runtime_factory import build_direct_service_runtime
from backend_manager.windows_user_security import show_elevated_manager_warning


def _run_elevated_service_action(
    action: ServiceAction,
    result_path: Path | None,
    result_root: Path | None,
    result_nonce: str | None,
    channel_owner_sid: str | None,
    channel_file_id: str | None,
) -> int:
    if not is_process_elevated():
        return HELPER_EXIT_NOT_ELEVATED
    if (
        result_path is None
        or result_root is None
        or result_nonce is None
        or channel_owner_sid is None
        or channel_file_id is None
    ):
        return HELPER_EXIT_CONFIG
    watchdog: threading.Event | None = None
    exit_code = 0
    diagnostic = "Ticketbox Windows 服务操作已完成。"
    try:
        validate_helper_result_channel(
            result_path,
            result_root,
            result_nonce,
            action,
            channel_owner_sid,
            channel_file_id,
        )
        with hold_installer_lifecycle_lock():
            config = load_config(mode_override="installed")
            runtime_config = config.runtime
            if not isinstance(runtime_config, InstalledRuntimeConfig):
                raise ConfigError("未找到正式安装运行时。")
            watchdog = start_helper_watchdog(
                timeout_seconds=runtime_config.release.helper_watchdog_seconds(action),
            )
            validate_installed_service_contract(runtime_config.layout, runtime_config.release)
            runtime = build_direct_service_runtime(
                config,
                runtime_config,
                backend_stopped_validator=partial(
                    validate_installed_backend_stopped,
                    runtime_config.layout,
                    runtime_config.release,
                ),
            )
            getattr(runtime, action)()
    except LifecycleBusyError as exc:
        exit_code, diagnostic = HELPER_EXIT_LIFECYCLE_BUSY, str(exc)
    except (ConfigError, InstallationConfigError) as exc:
        exit_code, diagnostic = HELPER_EXIT_CONFIG, str(exc)
    except ServiceMissingError as exc:
        exit_code, diagnostic = HELPER_EXIT_MISSING_SERVICE, str(exc)
    except ServiceTransitionError as exc:
        exit_code, diagnostic = HELPER_EXIT_TRANSITION, str(exc)
    except ServiceAccessError as exc:
        exit_code, diagnostic = HELPER_EXIT_ACCESS, str(exc)
    except (OSError, RuntimeControlError) as exc:
        exit_code, diagnostic = HELPER_EXIT_OS, str(exc)
    finally:
        if watchdog is not None:
            watchdog.set()
    try:
        write_helper_result(
            result_path,
            result_root,
            result_nonce,
            action,
            channel_owner_sid,
            channel_file_id,
            exit_code,
            diagnostic,
        )
    except RuntimeControlError:
        return HELPER_EXIT_OS if exit_code == 0 else exit_code
    return exit_code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--elevated-service-action", choices=("start", "stop", "restart"))
    parser.add_argument("--helper-result-path", type=Path)
    parser.add_argument("--helper-result-root", type=Path)
    parser.add_argument("--helper-result-nonce")
    parser.add_argument("--helper-channel-owner-sid")
    parser.add_argument("--helper-channel-file-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.elevated_service_action:
        return _run_elevated_service_action(
            args.elevated_service_action,
            args.helper_result_path,
            args.helper_result_root,
            args.helper_result_nonce,
            args.helper_channel_owner_sid,
            args.helper_channel_file_id,
        )
    if is_process_elevated():
        show_elevated_manager_warning()
        return 2

    try:
        config = load_config()
    except ConfigError as exc:
        identity = load_frozen_manager_identity()
        if identity is None:
            raise
        config = load_maintenance_manager_config(
            identity.version,
            startup_failure_code=exc.code,
            startup_failure_stage="runtime_discovery",
        )
    return run_manager(config)


if __name__ == "__main__":
    raise SystemExit(main())
