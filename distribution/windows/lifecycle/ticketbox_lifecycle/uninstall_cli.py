"""Administrator-only controlled default uninstall entry (preserves data and identity)."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

from ticketbox_lifecycle import command_io
from ticketbox_lifecycle.domain import uninstall as uninstall_action
from ticketbox_lifecycle.errors import LifecycleError, LifecycleViolation
from ticketbox_lifecycle.runtime import windows_shipment
from ticketbox_lifecycle.runtime.command import SubprocessCommandRunner
from ticketbox_lifecycle.runtime.filesystem_stores import FilesystemStores
from ticketbox_lifecycle.runtime.windows_known_folders import (
    ticketbox_install_root,
    ticketbox_program_data_root,
)
from ticketbox_lifecycle.runtime.windows_scm_observation import NativeWindowsScmObserver
from ticketbox_lifecycle.runtime.windows_security_native import require_windows
from ticketbox_lifecycle.runtime.windows_shipment import _absolute_path_key
from ticketbox_lifecycle.runtime.windows_uninstall import WindowsUninstallPlatform
from ticketbox_lifecycle.schemas import REQUEST_SCHEMA, RESULT_SCHEMA, CommandResult, InstallRequest


def _run_preflight_check() -> int:
    try:
        require_windows()
        expected_app_dir = ticketbox_install_root()
        expected_program_data = ticketbox_program_data_root()
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError(
                "uninstall_admin_required",
                "controlled uninstall requires an administrator",
            )
        fs_stores = FilesystemStores.from_installed(
            install_root=expected_app_dir,
            program_data_root=expected_program_data,
        )
        uninstall_action.check_uninstall_preflight(
            fs_stores.as_lifecycle_stores(),
            expected_data_root=str(expected_program_data / "data"),
            expected_pg_service_name=windows_shipment.PG_SERVICE_NAME,
            expected_backend_service_name=windows_shipment.BACKEND_SERVICE_NAME,
            expected_pg_port=windows_shipment.PG_PORT,
            expected_backend_port=windows_shipment.BACKEND_PORT,
            expected_postgres_major=windows_shipment.POSTGRES_MAJOR,
        )
        return 0
    except LifecycleError as exc:
        command_io.emit_failure(
            CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command="uninstall",
                operation_id="preflight",
                phase="failed_recoverable",
                code=exc.code,
                message=exc.message,
                installation_published=None,
            )
        )
        return 2
    except Exception:
        command_io.emit_failure(
            CommandResult(
                schema=RESULT_SCHEMA,
                ok=False,
                command="uninstall",
                operation_id="preflight",
                phase="failed_recoverable",
                code="unhandled",
                message="unexpected controlled uninstall preflight failure",
                installation_published=None,
            )
        )
        return 2


def _parse_uninstall_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="TicketboxLifecycle",
        description="Controlled uninstall of Ticketbox services while preserving database, originals, backups and identity",
    )
    parser.add_argument("command", choices=("uninstall",))
    parser.add_argument("--request", required=False, default=None)
    parser.add_argument("--result", required=False, default=None)
    parser.add_argument("--check-preflight", action="store_true")
    parser.add_argument("--from-installed", action="store_true")
    args = parser.parse_args(argv)
    if args.check_preflight:
        if args.request is not None or args.result is not None or args.from_installed:
            parser.error("--check-preflight does not accept --request, --result, or --from-installed")
        return args
    if args.from_installed:
        if args.request is not None or args.result is None or not args.result:
            parser.error("--from-installed requires --result and does not accept --request")
        return args
    if args.request is None or not args.request or args.result is None or not args.result:
        parser.error("--request and --result are required unless --check-preflight or --from-installed is specified")
    return args


def _write_running_receipt(result_path: Path, operation_id: str) -> None:
    command_io.write_result(
        result_path,
        CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="uninstall",
            operation_id=operation_id,
            phase="prepared",
            code="running",
            message="controlled uninstall started",
            installation_published=True,
        ),
    )


def _prepare_from_installed(
    *,
    expected_app_dir: Path,
    expected_program_data: Path,
    result_path: Path,
    forbidden_roots: list[Path],
) -> tuple[FilesystemStores, InstallRequest]:
    fs_stores = FilesystemStores.from_installed(
        install_root=expected_app_dir,
        program_data_root=expected_program_data,
    )
    binding = fs_stores.read()
    if binding is not None and binding.data_root:
        forbidden_roots.append(Path(binding.data_root))
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
    if binding is None or not uninstall_action._is_sha256_hex(binding.release_manifest_sha256):
        raise LifecycleViolation(
            "uninstall_binding_missing",
            "controlled uninstall requires a verified installation.json; refusing unbound deletion",
        )
    manifest_sha = binding.release_manifest_sha256.lower()
    request = InstallRequest(
        schema=REQUEST_SCHEMA,
        command="uninstall",
        operation_id=f"uninstall-{manifest_sha}",
        request_hash="pending",
        target_release_id=binding.active_release_id,
        app_dir=str(expected_app_dir),
        data_root=str(expected_program_data / "data"),
        program_data_root=str(expected_program_data),
        pg_service_name=windows_shipment.PG_SERVICE_NAME,
        backend_service_name=windows_shipment.BACKEND_SERVICE_NAME,
        pg_port=windows_shipment.PG_PORT,
        backend_port=windows_shipment.BACKEND_PORT,
        postgres_major=windows_shipment.POSTGRES_MAJOR,
        release_manifest_sha256=manifest_sha,
        install_id=binding.install_id,
        dataset_id=binding.dataset_id,
    )
    forbidden_roots.append(Path(request.data_root))
    command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
    return fs_stores, request


def _prepare_from_request(
    request_path: str,
    *,
    expected_app_dir: Path,
    expected_program_data: Path,
    result_path: Path,
    forbidden_roots: list[Path],
    operation_id_box: list[str],
) -> tuple[FilesystemStores, InstallRequest]:
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    operation_id_box[0] = str(payload.get("operation_id") or "unknown")
    request = command_io.parse_request(payload, command="uninstall")
    operation_id_box[0] = request.operation_id
    forbidden_roots.extend([
        Path(request.app_dir),
        Path(request.program_data_root),
        Path(request.data_root),
    ])
    command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
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
    return fs_stores, request


def main(argv: list[str]) -> int:
    args = _parse_uninstall_args(argv)
    if args.check_preflight:
        return _run_preflight_check()
    result_path = Path(args.result)
    operation_id_box = ["unknown"]
    forbidden_roots: list[Path] = []
    forbidden_roots_ready = False
    result_path_safe = False
    try:
        require_windows()
        expected_app_dir, expected_program_data, forbidden_roots = command_io.resolve_default_forbidden_roots(
            install_root_fn=ticketbox_install_root,
            program_data_root_fn=ticketbox_program_data_root,
        )
        assert expected_app_dir is not None and expected_program_data is not None
        forbidden_roots_ready = True
        command_io.require_safe_result_path(result_path, forbidden_roots=forbidden_roots)
        if not ctypes.windll.shell32.IsUserAnAdmin():
            raise LifecycleError("uninstall_admin_required", "controlled uninstall requires an administrator")
        if args.from_installed:
            fs_stores, request = _prepare_from_installed(
                expected_app_dir=expected_app_dir,
                expected_program_data=expected_program_data,
                result_path=result_path,
                forbidden_roots=forbidden_roots,
            )
            operation_id_box[0] = request.operation_id
        else:
            fs_stores, request = _prepare_from_request(
                args.request,
                expected_app_dir=expected_app_dir,
                expected_program_data=expected_program_data,
                result_path=result_path,
                forbidden_roots=forbidden_roots,
                operation_id_box=operation_id_box,
            )
        result_path_safe = True
        _write_running_receipt(result_path, operation_id_box[0])
        platform = WindowsUninstallPlatform(SubprocessCommandRunner(), NativeWindowsScmObserver())
        result = uninstall_action.uninstall(fs_stores.as_lifecycle_stores(), request, platform)
    except LifecycleError as exc:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="uninstall",
            operation_id=operation_id_box[0],
            phase="failed_recoverable",
            code=exc.code,
            message=exc.message,
            installation_published=True,
        )
    except Exception:
        result = CommandResult(
            schema=RESULT_SCHEMA,
            ok=False,
            command="uninstall",
            operation_id=operation_id_box[0],
            phase="failed_recoverable",
            code="unhandled",
            message="unexpected controlled uninstall failure",
            installation_published=True,
        )
    if forbidden_roots_ready and (result_path_safe or result.code != "unsafe_result_path"):
        command_io.write_result_if_safe(result_path, result, forbidden_roots=forbidden_roots)
    if not result.ok:
        command_io.emit_failure(result)
    return 0 if result.ok else 2
