"""Administrator-only managed existing-dataset upgrade entry."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
from typing import cast

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain import upgrade as upgrade_action
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_dataset import WindowsDatasetAdapter
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm import WindowsScmAdapter
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_security import WindowsSecurityAdapter
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.runtime.windows_shipment import _absolute_path_key
from ticketbox_lifecycle.runtime.windows_upgrade import WindowsUpgradePlatform
from ticketbox_lifecycle.schemas import RESULT_SCHEMA, CommandResult, DurablePhase, InstallRequest


def _read_durable_failure_status(
    fs_stores: FilesystemStores | None,
    request: InstallRequest | None,
    operation_id: str,
) -> tuple[DurablePhase, bool | None]:
    if fs_stores is None or request is None:
        return "failed_recoverable", None
    published: bool | None = False
    phase: DurablePhase = "failed_recoverable"
    try:
        binding = fs_stores.read()
    except Exception:
        published = None
        binding = None
    if (
        binding is not None
        and binding.active_release_id == request.target_release_id
        and binding.release_manifest_sha256 == request.release_manifest_sha256
    ):
        published = True
    try:
        committed = fs_stores.read_committed(operation_id)
    except Exception:
        committed = None
    if committed is not None:
        phase = "committed"
    else:
        try:
            active = fs_stores.read_active()
        except Exception:
            active = None
        if active is not None and active.operation_id == operation_id and active.phase == "committed":
            phase = "committed"
    return phase, published


def _load_upgrade_request_and_stores(
    request_path: str,
    command: str,
    *,
    expected_app_dir: Path,
    expected_program_data: Path,
    forbidden_roots: list[Path],
    protected_files: list[Path],
    operation_id_box: list[str],
) -> tuple[InstallRequest, FilesystemStores]:
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    operation_id_box[0] = str(payload.get("operation_id") or "unknown")
    request = command_io.parse_request(payload, command=command)
    operation_id_box[0] = request.operation_id
    forbidden_roots.extend([
        Path(request.app_dir),
        Path(request.program_data_root),
        Path(request.data_root),
    ])
    if _absolute_path_key(Path(request.app_dir)) != _absolute_path_key(expected_app_dir):
        raise LifecycleViolation(
            "untrusted_install_root",
            "installed application root must be the exact Ticketbox Program Files directory",
        )
    if _absolute_path_key(Path(request.program_data_root)) != _absolute_path_key(expected_program_data):
        raise LifecycleViolation(
            "untrusted_setup_request",
            "privileged request does not match the trusted ProgramData root",
        )
    fs_stores = FilesystemStores.from_request(
        request,
        install_root=expected_app_dir,
        program_data_root=expected_program_data,
    )
    try:
        existing_active = fs_stores.read_active()
    except Exception:
        existing_active = None
    if existing_active is not None:
        backup_path = getattr(existing_active, "backup_path", "")
        if isinstance(backup_path, str) and backup_path:
            protected_files.append(Path(backup_path))
    return request, fs_stores


def _build_upgrade_platform(
    fs_stores: FilesystemStores,
    *,
    expected_app_dir: Path,
    expected_program_data: Path,
    staged_root: Path | None,
) -> WindowsUpgradePlatform:
    return WindowsUpgradePlatform(
        fs_stores,
        SubprocessCommandRunner(),
        cast(WindowsSecurityAdapter, fs_stores._adapters.security),
        cast(WindowsScmAdapter, fs_stores._adapters.scm),
        NativeWindowsScmObserver(),
        cast(WindowsDatasetAdapter, fs_stores._adapters.dataset),
        expected_app_dir=expected_app_dir,
        expected_program_data_root=expected_program_data,
        staged_release_root=staged_root,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        description="Managed upgrade and pre-write failure rollback for an existing Windows Ticketbox installation",
    )
    parser.add_argument("command", choices=("upgrade", "rollback-upgrade"))
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--staged-release-root", default="")
    parser.add_argument("--rollback-on-failure", action="store_true", default=False)
    args = parser.parse_args(argv)
    result_path = Path(args.result)
    staged_root = Path(args.staged_release_root) if args.staged_release_root else None
    operation_id_box = ["unknown"]
    request: InstallRequest | None = None
    fs_stores: FilesystemStores | None = None
    forbidden_roots: list[Path] = []
    protected_files: list[Path] = []
    forbidden_roots_ready = False
    result_path_safe = False
    try:
        require_windows()
        expected_app_dir, expected_program_data, forbidden_roots = command_io.resolve_default_forbidden_roots(
            install_root_fn=ticketbox_install_root,
            program_data_root_fn=ticketbox_program_data_root,
        )
        assert expected_app_dir is not None and expected_program_data is not None
        if staged_root is not None:
            forbidden_roots.append(staged_root)
        forbidden_roots_ready = True
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("upgrade_admin_required", "managed upgrade requires an administrator")
        request, fs_stores = _load_upgrade_request_and_stores(
            args.request,
            args.command,
            expected_app_dir=expected_app_dir,
            expected_program_data=expected_program_data,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
            operation_id_box=operation_id_box,
        )
        command_io.require_safe_result_path(
            result_path,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
        result_path_safe = True
        command_io.write_result(
            result_path,
            CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command=args.command,
                operation_id=operation_id_box[0],
                phase="prepared",
                code="running",
                message=f"{args.command} started",
                installation_published=None,
            ),
        )
        platform = _build_upgrade_platform(
            fs_stores,
            expected_app_dir=expected_app_dir,
            expected_program_data=expected_program_data,
            staged_root=staged_root,
        )
        lifecycle_stores = fs_stores.as_lifecycle_stores()
        if args.command == "rollback-upgrade":
            result = upgrade_action.rollback_upgrade(lifecycle_stores, request, platform)
        else:
            result = upgrade_action.upgrade(
                lifecycle_stores,
                request,
                platform,
                rollback_on_failure=bool(args.rollback_on_failure),
            )
    except LifecycleError as exc:
        phase, published = _read_durable_failure_status(fs_stores, request, operation_id_box[0])
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=operation_id_box[0],
            phase=phase,
            code=exc.code,
            message=exc.message,
            installation_published=published,
        )
    except Exception:
        phase, published = _read_durable_failure_status(fs_stores, request, operation_id_box[0])
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command=args.command,
            operation_id=operation_id_box[0],
            phase=phase,
            code="unhandled",
            message="unexpected managed upgrade failure",
            installation_published=published,
        )
    if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
        command_io.write_result_if_safe(
            result_path,
            result,
            forbidden_roots=forbidden_roots,
            protected_files=protected_files,
        )
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
