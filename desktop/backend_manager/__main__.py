"""Desktop Manager entry point for source and installed-service runtimes."""

from __future__ import annotations

import argparse
import sys

from backend_manager.build_identity import FrozenManagerIdentity, load_frozen_manager_identity
from backend_manager.config import (
    ConfigError,
    load_config,
    load_maintenance_manager_config,
)
from backend_manager.manager_startup import run_manager
from backend_manager.runtime import RuntimeControlError
from backend_manager.windows_user_security import (
    is_process_elevated,
    show_elevated_manager_warning,
    show_manager_repair_required_warning,
    show_manager_startup_failure_warning,
)


def _load_validated_frozen_identity() -> FrozenManagerIdentity | None:
    identity = load_frozen_manager_identity()
    if getattr(sys, "frozen", False) and identity is None:
        raise ConfigError(
            "桌面管理器载荷身份无效，请使用可信安装包执行修复。",
            code="manager_identity_invalid",
        )
    return identity


def _parse_args(argv: list[str] | None) -> None:
    argparse.ArgumentParser(add_help=False).parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    if is_process_elevated():
        show_elevated_manager_warning()
        return 2

    try:
        identity = _load_validated_frozen_identity()
    except ConfigError:
        show_manager_repair_required_warning()
        return 3
    try:
        config = load_config()
    except ConfigError as exc:
        if identity is None:
            raise
        config = load_maintenance_manager_config(
            identity.version,
            startup_failure_code=exc.code,
            startup_failure_stage="runtime_discovery",
        )
    else:
        if identity is not None and config.expected_backend_version != identity.version:
            config = load_maintenance_manager_config(
                identity.version,
                startup_failure_code="manager_identity_mismatch",
                startup_failure_stage="manager_identity",
            )
    try:
        return run_manager(config)
    except (ConfigError, OSError, RuntimeControlError) as exc:
        if identity is None:
            raise
        show_manager_startup_failure_warning(str(exc))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
