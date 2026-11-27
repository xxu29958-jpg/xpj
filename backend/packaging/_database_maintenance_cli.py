"""CLI argument parsing and mode runners for ticketbox-database-maintenance.exe."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, TextIO

FRESH_SCHEMA_UPGRADE_SWITCH = "--fresh-schema-upgrade"
EXISTING_DATASET_UPGRADE_SWITCH = "--upgrade-existing-dataset"
FRESH_OWNER_CLAIM_SWITCH = "--fresh-owner-claim"
COLD_RESTORE_SWITCH = "--restore-cold-dataset"
VERIFY_PRESERVED_DATASET_SWITCH = "--verify-preserved-dataset"
DATABASE_GENERATION_TARGET_VERIFY_SWITCH = "--database-generation-verify-target"
GENERATION_PROGRAM_VALIDATE_SWITCH = "--validate-generation-program"

EXISTING_DATASET_UPGRADE_RESULT_FIELDS = (
    "schema",
    "operation_id",
    "dataset_id",
    "installation_id",
    "restore_epoch",
    "source_revision",
    "target_revision",
    "alembic_revision",
    "backup_archive_sha256",
    "result",
)
GENERATION_PROGRAM_VALIDATION_FIELDS = (
    "schema",
    "source_revision",
    "target_revision",
    "revision_count",
    "generation_program_sha256",
)
FRESH_SCHEMA_RESULT_FIELDS = (
    "schema",
    "target_revision",
    "alembic_revision",
    "dataset_id",
    "client_generation",
    "result",
)
FRESH_OWNER_RESULT_FIELDS = (
    "contract",
    "operation_id",
    "installation_id",
    "account_name",
    "ledger_id",
    "ledger_name",
    "device_name",
    "pairing_code",
    "pairing_expires_at",
    "pairing_derivation_index",
    "claim_generation",
)


def _add_generation_program_arguments(parser: ArgumentParser) -> None:
    parser.add_argument("--generation-program-path", type=Path, required=True)
    parser.add_argument("--expected-generation-program-sha256", required=True)


def parse_generation_program_validation_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(GENERATION_PROGRAM_VALIDATE_SWITCH, action="store_true", required=True)
    _add_generation_program_arguments(parser)
    return parser.parse_args(argv)


def parse_fresh_schema_upgrade_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(FRESH_SCHEMA_UPGRADE_SWITCH, action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--client-generation", required=True)
    parser.add_argument("--schema-min-compatible", required=True)
    parser.add_argument("--semantic-revision", required=True)
    parser.add_argument("--operation-id", required=True)
    return parser.parse_args(argv)


def parse_existing_dataset_upgrade_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(EXISTING_DATASET_UPGRADE_SWITCH, action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--expected-restore-epoch", type=int, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--backup-archive", type=Path, required=True)
    parser.add_argument("--backup-archive-sha256", required=True)
    parser.add_argument("--app-dir", type=Path, default=None)
    return parser.parse_args(argv)


def parse_fresh_owner_claim_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(FRESH_OWNER_CLAIM_SWITCH, action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--installation-id", required=True)
    return parser.parse_args(argv)


def parse_database_generation_target_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(
        prog="ticketbox-database-maintenance",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument(DATABASE_GENERATION_TARGET_VERIFY_SWITCH, action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    _add_generation_program_arguments(parser)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--restore-attempt-id", default="")
    parser.add_argument("--target-revision", required=True)
    return parser.parse_args(argv)


def _require_streams(
    input_stream: BinaryIO | None,
    output_stream: TextIO | None,
    *,
    label: str,
) -> tuple[BinaryIO, TextIO]:
    resolved_in = sys.stdin.buffer if input_stream is None else input_stream
    resolved_out = sys.stdout if output_stream is None else output_stream
    if resolved_in is None or resolved_out is None:
        raise RuntimeError(f"{label} requires redirected stdin/stdout")
    return resolved_in, resolved_out


def run_generation_program_validation(
    argv: list[str],
    *,
    load_module: Callable[[], ModuleType],
    resolve_program: Callable[[Path], Path],
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Validate the build-owned program without opening PostgreSQL."""

    args = parse_generation_program_validation_args(argv)
    stdin_stream, stdout_stream = _require_streams(
        input_stream, output_stream, label="generation program validation"
    )
    if stdin_stream.read(1) != b"":
        raise RuntimeError("generation program validation requires empty stdin")
    validation = load_module()
    result = validation.validate_database_generation_program(
        generation_program_path=resolve_program(args.generation_program_path),
        expected_generation_program_sha256=args.expected_generation_program_sha256,
    )
    if tuple(result) != GENERATION_PROGRAM_VALIDATION_FIELDS:
        raise RuntimeError("generation program validation returned an unsupported shape")
    stdout_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout_stream.flush()
    return 0


def run_fresh_schema_upgrade(
    argv: list[str],
    *,
    assert_libpq: Callable[[Path], None],
    load_module: Callable[[], ModuleType],
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = parse_fresh_schema_upgrade_args(argv)
    stdin_stream, stdout_stream = _require_streams(
        input_stream, output_stream, label="fresh schema upgrade"
    )
    if stdin_stream.read(1) != b"":
        raise RuntimeError("fresh schema upgrade requires empty stdin")
    assert_libpq(args.pgpassfile)
    module = load_module()
    result = module.run_fresh_schema_upgrade_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        target_revision=args.target_revision,
        dataset_id=args.dataset_id,
        client_generation=args.client_generation,
        schema_min_compatible=args.schema_min_compatible,
        semantic_revision=args.semantic_revision,
        operation_id=args.operation_id,
    )
    if tuple(result) != FRESH_SCHEMA_RESULT_FIELDS:
        raise RuntimeError("fresh schema upgrade returned an unsupported result shape")
    stdout_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout_stream.flush()
    return 0


def run_existing_dataset_upgrade(
    argv: list[str],
    *,
    assert_libpq: Callable[[Path], None],
    load_module: Callable[[], ModuleType],
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = parse_existing_dataset_upgrade_args(argv)
    stdin_stream, stdout_stream = _require_streams(
        input_stream, output_stream, label="existing dataset upgrade"
    )
    if stdin_stream.read(1) != b"":
        raise RuntimeError("existing dataset upgrade requires empty stdin")
    assert_libpq(args.pgpassfile)
    module = load_module()
    result = module.run_existing_dataset_upgrade_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        source_revision=args.source_revision,
        target_revision=args.target_revision,
        dataset_id=args.dataset_id,
        installation_id=args.installation_id,
        expected_restore_epoch=args.expected_restore_epoch,
        operation_id=args.operation_id,
        data_root=args.data_root,
        backup_archive=args.backup_archive,
        backup_archive_sha256=args.backup_archive_sha256,
        app_dir=args.app_dir,
    )
    if tuple(result) != EXISTING_DATASET_UPGRADE_RESULT_FIELDS:
        raise RuntimeError("existing dataset upgrade returned an unsupported result shape")
    stdout_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout_stream.flush()
    return 0


def run_fresh_owner_claim(
    argv: list[str],
    *,
    assert_libpq: Callable[[Path], None],
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = parse_fresh_owner_claim_args(argv)
    stdin_stream, stdout_stream = _require_streams(
        input_stream, output_stream, label="fresh owner claim"
    )
    raw_secret = stdin_stream.read(257)
    if len(raw_secret) > 256:
        raise RuntimeError("fresh owner claim secret is too long")
    try:
        secret = raw_secret.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("fresh owner claim secret is invalid") from exc
    if not 32 <= len(secret) <= 256 or any(character.isspace() for character in secret):
        raise RuntimeError("fresh owner claim secret is invalid")
    assert_libpq(args.pgpassfile)
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.services.identity_service import bootstrap_installation_owner
    from app.services.secure_file import hold_installer_machine_secret_for_read

    with hold_installer_machine_secret_for_read(args.pgpassfile):
        engine = create_engine(
            args.database_url,
            connect_args={"connect_timeout": 10, "options": "-c timezone=utc"},
            pool_pre_ping=True,
            future=True,
        )
        try:
            with Session(engine, expire_on_commit=False) as db:
                db.execute(text("SET ROLE ticketbox_owner"))
                result = bootstrap_installation_owner(
                    db,
                    operation_id=args.operation_id,
                    installation_id=args.installation_id,
                    bootstrap_secret=secret,
                    account_name="我",
                    ledger_name="我的小票夹",
                    device_name="Windows 安装来源",
                    commit=False,
                )
                db.commit()
        finally:
            engine.dispose()
    payload = asdict(result)
    if tuple(payload) != FRESH_OWNER_RESULT_FIELDS:
        raise RuntimeError("fresh owner claim returned an unsupported result shape")
    stdout_stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout_stream.flush()
    return 0


def run_database_generation_target_verification(
    argv: list[str],
    *,
    assert_libpq: Callable[[Path], None],
    load_module: Callable[[], ModuleType],
    resolve_program: Callable[[Path], Path],
    input_stream: BinaryIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Prove revision, schema shape, and money facts for one database target."""

    args = parse_database_generation_target_args(argv)
    stdin_stream, stdout_stream = _require_streams(
        input_stream, output_stream, label="target verification"
    )
    if stdin_stream.read(1) != b"":
        raise RuntimeError("database generation target verification requires empty stdin")
    assert_libpq(args.pgpassfile)
    target = load_module()
    result = target.run_database_generation_target_verification_action(
        database_url=args.database_url,
        pgpassfile=args.pgpassfile,
        generation_program_path=resolve_program(args.generation_program_path),
        expected_generation_program_sha256=args.expected_generation_program_sha256,
        operation_id=args.operation_id,
        database=args.database,
        restore_attempt_id=args.restore_attempt_id,
        target_revision=args.target_revision,
    )
    stdout_stream.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n")
    stdout_stream.flush()
    return 0
