"""Closed CLI codec and action adapter for H2 dataset maintenance."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import BinaryIO, TextIO

from app.database_maintenance_runtime import (
    DatabaseMaintenanceContractError,
    assert_maintenance_libpq_environment,
    load_standalone_database_module,
    resolve_generation_program,
)

_COMPLETE_DATASET_BACKUP_SWITCH = "--complete-dataset-backup"
_INSPECT_DATASET_BACKUP_SWITCH = "--inspect-dataset-backup"
_ISOLATED_DATASET_RESTORE_SWITCH = "--isolated-dataset-restore"
_VERIFY_RESTORED_ORIGINALS_SWITCH = "--verify-restored-originals"
DATASET_MAINTENANCE_SWITCHES = (
    _COMPLETE_DATASET_BACKUP_SWITCH,
    _INSPECT_DATASET_BACKUP_SWITCH,
    _ISOLATED_DATASET_RESTORE_SWITCH,
    _VERIFY_RESTORED_ORIGINALS_SWITCH,
)


def _parser() -> ArgumentParser:
    return ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )


def _add_generation_program_arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--generation-program-path", type=Path, required=True)
    parser.add_argument("--expected-generation-program-sha256", required=True)


def _parse_complete_dataset_backup_args(argv: list[str]) -> Namespace:
    parser = _parser()
    parser.add_argument(_COMPLETE_DATASET_BACKUP_SWITCH, action="store_true", required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--inventory-path", type=Path, required=True)
    parser.add_argument("--upload-root", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--pg-dump-path", type=Path, required=True)
    parser.add_argument("--pg-restore-path", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--backup-kind", choices=("manual",), required=True)
    parser.add_argument("--writer-fence-sha256", required=True)
    parser.add_argument("--expected-current-sha256", required=True)
    parser.add_argument("--expected-installation-id", required=True)
    parser.add_argument("--expected-dataset-id", required=True)
    parser.add_argument("--expected-restore-epoch", type=int, required=True)
    parser.add_argument("--expected-schema-revision", required=True)
    return parser.parse_args(argv)


def _parse_dataset_backup_inspection_args(argv: list[str]) -> Namespace:
    parser = _parser()
    parser.add_argument(_INSPECT_DATASET_BACKUP_SWITCH, action="store_true", required=True)
    parser.add_argument("--backup-generation", type=Path, required=True)
    return parser.parse_args(argv)


def _parse_isolated_dataset_restore_args(argv: list[str]) -> Namespace:
    parser = _parser()
    parser.add_argument(_ISOLATED_DATASET_RESTORE_SWITCH, action="store_true", required=True)
    parser.add_argument("--backup-generation", type=Path, required=True)
    parser.add_argument("--target-upload-root", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--pg-restore-path", type=Path, required=True)
    parser.add_argument("--active-installation-id", required=True)
    parser.add_argument("--active-dataset-id", required=True)
    parser.add_argument("--active-restore-epoch", type=int, required=True)
    parser.add_argument("--target-schema-revision", required=True)
    parser.add_argument("--restore-role", required=True)
    _add_generation_program_arguments(parser)
    parser.add_argument("--operation-id", required=True)
    return parser.parse_args(argv)


def _parse_restored_originals_verification_args(argv: list[str]) -> Namespace:
    parser = _parser()
    parser.add_argument(_VERIFY_RESTORED_ORIGINALS_SWITCH, action="store_true", required=True)
    parser.add_argument("--backup-generation", type=Path, required=True)
    parser.add_argument("--restored-upload-root", type=Path, required=True)
    return parser.parse_args(argv)


def _load_complete_dataset_backup_module():
    return load_standalone_database_module(
        module_name="_ticketbox_complete_dataset_backup",
        filename="_dataset_backup_action.py",
        database_package_seam=True,
    )


def _load_isolated_dataset_restore_module():
    return load_standalone_database_module(
        module_name="_ticketbox_isolated_dataset_restore",
        filename="_dataset_restore_action.py",
        database_package_seam=True,
    )


def _streams(
    input_stream: BinaryIO | None,
    output_stream: TextIO | None,
    *,
    label: str,
) -> tuple[BinaryIO, TextIO]:
    resolved_input = input_stream if input_stream is not None else sys.stdin.buffer
    resolved_output = output_stream if output_stream is not None else sys.stdout
    if resolved_input is None or resolved_output is None:
        raise DatabaseMaintenanceContractError(f"{label} requires redirected IO")
    if resolved_input.read(1) != b"":
        raise DatabaseMaintenanceContractError(f"{label} requires empty stdin")
    return resolved_input, resolved_output


def _write_result(output: TextIO, result: dict[str, object]) -> None:
    output.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    output.flush()


def _run_complete_dataset_backup(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_complete_dataset_backup_args(argv)
    _input, output = _streams(input_stream, output_stream, label="complete dataset backup")
    assert_maintenance_libpq_environment(args.pgpassfile)
    module = _load_complete_dataset_backup_module()
    from app.services.backup_service import CompleteBackupRequest

    result = module.run_complete_dataset_backup_action(
        CompleteBackupRequest(
            backup_root=args.backup_root,
            inventory_path=args.inventory_path,
            upload_root=args.upload_root,
            database_url=args.database_url,
            passfile=args.pgpassfile,
            pg_dump_binary=args.pg_dump_path,
            pg_restore_binary=args.pg_restore_path,
            operation_id=args.operation_id,
            backup_id=args.backup_id,
            release_id=args.release_id,
            backup_kind=args.backup_kind,
            writer_fence_sha256=args.writer_fence_sha256,
            expected_current_sha256=args.expected_current_sha256,
            expected_installation_id=args.expected_installation_id,
            expected_dataset_id=args.expected_dataset_id,
            expected_restore_epoch=args.expected_restore_epoch,
            expected_schema_revision=args.expected_schema_revision,
        )
    )
    if tuple(result) != module.RESULT_FIELDS:
        raise DatabaseMaintenanceContractError("complete dataset backup returned an unsupported shape")
    _write_result(output, result)
    return 0


def _run_dataset_backup_inspection(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_dataset_backup_inspection_args(argv)
    _input, output = _streams(input_stream, output_stream, label="dataset backup inspection")
    module = _load_complete_dataset_backup_module()
    result = module.inspect_complete_dataset_backup_action(args.backup_generation)
    if tuple(result) != module.INSPECTION_FIELDS:
        raise DatabaseMaintenanceContractError("dataset backup inspection returned an unsupported shape")
    _write_result(output, result)
    return 0


def _run_isolated_dataset_restore(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_isolated_dataset_restore_args(argv)
    _input, output = _streams(input_stream, output_stream, label="isolated dataset restore")
    assert_maintenance_libpq_environment(args.pgpassfile)
    module = _load_isolated_dataset_restore_module()
    from app.services.dataset_restore_service import CompleteRestoreRequest

    result = module.run_verified_isolated_dataset_restore_action(
        request=CompleteRestoreRequest(
            backup_generation=args.backup_generation,
            target_upload_root=args.target_upload_root,
            database_url=args.database_url,
            passfile=args.pgpassfile,
            pg_restore_binary=args.pg_restore_path,
            active_installation_id=args.active_installation_id,
            active_dataset_id=args.active_dataset_id,
            active_restore_epoch=args.active_restore_epoch,
            target_schema_revision=args.target_schema_revision,
            restore_role=args.restore_role,
        ),
        generation_program_path=resolve_generation_program(args.generation_program_path),
        expected_generation_program_sha256=args.expected_generation_program_sha256,
        operation_id=args.operation_id,
    )
    if tuple(result) != module.RESULT_FIELDS:
        raise DatabaseMaintenanceContractError("isolated dataset restore returned an unsupported shape")
    _write_result(output, result)
    return 0


def _run_restored_originals_verification(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_restored_originals_verification_args(argv)
    _input, output = _streams(input_stream, output_stream, label="restored originals verification")
    module = _load_isolated_dataset_restore_module()
    result = module.verify_restored_originals_action(
        args.backup_generation,
        args.restored_upload_root,
    )
    if tuple(result) != module.RUNTIME_VERIFICATION_FIELDS:
        raise DatabaseMaintenanceContractError("restored originals verification returned an unsupported shape")
    _write_result(output, result)
    return 0


def run_dataset_maintenance(
    argv: list[str],
    *,
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    selected = [switch for switch in DATASET_MAINTENANCE_SWITCHES if switch in argv]
    if len(selected) != 1:
        raise DatabaseMaintenanceContractError("dataset maintenance helper accepts exactly one mode")
    runners = {
        _COMPLETE_DATASET_BACKUP_SWITCH: _run_complete_dataset_backup,
        _INSPECT_DATASET_BACKUP_SWITCH: _run_dataset_backup_inspection,
        _ISOLATED_DATASET_RESTORE_SWITCH: _run_isolated_dataset_restore,
        _VERIFY_RESTORED_ORIGINALS_SWITCH: _run_restored_originals_verification,
    }
    return runners[selected[0]](
        argv,
        input_stream=input_stream,
        output_stream=output_stream,
    )


__all__ = ["DATASET_MAINTENANCE_SWITCHES", "run_dataset_maintenance"]
