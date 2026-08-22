"""Complete Ticketbox dataset backup/restore recovery drill.

Proves the installed backup owner emits an all-or-nothing database plus
original-attachment generation. It then runs the complete isolated restore
action, including attachment materialization, sanitation, and Dataset Authority
publication, before comparing preserved database rows and exact original bytes.

Runs on the backend-postgres CI lane right after the smoke test (which populates
the source DB). Not needed locally.

    DRILL_SOURCE_URL=postgresql+psycopg://...:.../xpj_smoke?require_auth=scram-sha-256 \
    DRILL_RESTORE_URL=postgresql+psycopg://...:.../xpj_restore?require_auth=scram-sha-256 \
        python scripts/postgres_backup_drill.py --upload-root /absolute/uploads
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from psycopg import Connection
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.path_entry_safety import is_link_or_reparse  # noqa: E402
from scripts.postgres_dataset_facts import DatabaseFacts, read_database_facts  # noqa: E402
from scripts.postgres_frozen_restore_drill import (  # noqa: E402
    restore_with_frozen_helper,
)
from scripts.postgres_restore_drill_topology import (  # noqa: E402
    managed_restore_role_topology,
)
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT  # noqa: E402
from scripts.test_postgres_database import dedicated_test_database_lease  # noqa: E402


@dataclass(frozen=True)
class _DrillInputs:
    source_url: str
    restore_url: str
    upload_root: Path
    passfile: Path
    pg_dump: Path
    pg_restore: Path
    cluster_identity: str
    frozen_restore_helper: Path | None


@contextmanager
def _leased_source_engine(source_url: str, source_connection: Connection) -> Iterator[Engine]:
    """Expose one real leased driver connection without transferring ownership."""

    original_autocommit = source_connection.autocommit
    source_engine: Engine | None = None
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        source_connection.autocommit = False
        source_engine = create_engine(
            source_url,
            creator=lambda: source_connection,
            poolclass=StaticPool,
        )
        yield source_engine
    except BaseException as exc:  # noqa: BLE001 - preserve drill and cleanup truth
        primary = exc
    finally:
        if source_engine is not None:
            try:
                source_engine.dispose(close=False)
            except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
                cleanup.append(exc)
        try:
            source_connection.autocommit = original_autocommit
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
            cleanup.append(exc)
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "PostgreSQL drill and leased source cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary
    if cleanup:
        if len(cleanup) == 1:
            raise cleanup[0]
        raise BaseExceptionGroup("leased PostgreSQL source cleanup failed", cleanup)


def _run_drill(
    source_url: str,
    restore_url: str,
    *,
    upload_root: Path,
    passfile: Path,
    cluster_identity: str,
    source_connection: Connection,
    frozen_restore_helper: Path | None,
) -> int:
    from app.database._dataset_restore_authority import SANITATION_TABLES
    from app.services.postgres_backup_validation_service import find_pg_binary

    pg_dump = find_pg_binary("pg_dump", "PG_DUMP_PATH")
    pg_restore = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not pg_dump or not pg_restore:
        raise SystemExit("FAIL drill: supported PostgreSQL backup tools not found")
    source_facts = read_database_facts(source_url)
    if source_facts.tables["expenses"].row_count == 0:
        raise SystemExit("FAIL drill: source has no expenses — did the smoke test run first?")
    inputs = _DrillInputs(
        source_url=source_url,
        restore_url=restore_url,
        upload_root=upload_root,
        passfile=passfile,
        pg_dump=Path(pg_dump).resolve(strict=True),
        pg_restore=Path(pg_restore).resolve(strict=True),
        cluster_identity=cluster_identity,
        frozen_restore_helper=frozen_restore_helper,
    )
    with (
        _leased_source_engine(source_url, source_connection) as source_engine,
        tempfile.TemporaryDirectory(prefix="ticketbox-dataset-drill-") as temporary,
    ):
        restored_facts = _exercise_complete_generation(
            inputs,
            source_engine,
            Path(temporary).resolve(),
        )
    _assert_restored_database(source_facts, restored_facts, SANITATION_TABLES)
    print("\nPASS postgres backup/restore drill")
    return 0


def _exercise_complete_generation(
    inputs: _DrillInputs,
    source_engine: Engine,
    temporary: Path,
) -> DatabaseFacts:
    generation, manifest = _create_complete_generation(inputs, source_engine, temporary)
    if inputs.frozen_restore_helper is not None:
        restored_facts, restored_originals = restore_with_frozen_helper(
            source_url=inputs.source_url,
            admin_url=os.environ["XPJ_TEST_ADMIN_URL"],
            admin_passfile=inputs.passfile,
            helper=inputs.frozen_restore_helper,
            pg_restore=inputs.pg_restore,
            temporary=temporary,
            generation=generation,
            manifest=manifest,
        )
        _assert_restored_originals(manifest, restored_originals)
        return restored_facts
    _restore_complete_generation(inputs, temporary, generation, manifest)
    return read_database_facts(inputs.restore_url)


def _create_complete_generation(
    inputs: _DrillInputs,
    source_engine: Engine,
    temporary: Path,
) -> tuple[Path, object]:
    from sqlalchemy.orm import Session

    from app.services.backup_service import CompleteBackupRequest, create_complete_backup_generation
    from app.services.dataset_authority_service import read_dataset_authority
    from app.services.dataset_backup_contract import read_manifest

    backup_root = temporary / "backups"
    with Session(source_engine) as authority_session:
        authority = read_dataset_authority(authority_session)
    current_sha256 = hashlib.sha256(f"test-only-current:{inputs.cluster_identity}".encode()).hexdigest()
    with Session(source_engine) as session:
        entry = create_complete_backup_generation(
            CompleteBackupRequest(
                backup_root=backup_root,
                inventory_path=temporary / "backup-inventory.json",
                upload_root=inputs.upload_root,
                database_url=inputs.source_url,
                passfile=inputs.passfile,
                pg_dump_binary=inputs.pg_dump,
                pg_restore_binary=inputs.pg_restore,
                operation_id=str(uuid4()),
                backup_id=str(uuid4()),
                release_id="ci-postgres-backup-drill",
                backup_kind="manual",
                writer_fence_sha256=_writer_fence_sha256(authority, current_sha256),
                expected_current_sha256=current_sha256,
                expected_installation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                expected_dataset_id=authority.dataset_id,
                expected_restore_epoch=authority.restore_epoch,
                expected_schema_revision=authority.schema_revision,
            ),
            db=session,
        )
    generation = backup_root / entry.file_name
    manifest = read_manifest(generation, verify_files=True)
    print(
        "OK complete dataset generation: "
        f"{entry.file_name} ({entry.size_bytes} bytes, {len(manifest.originals)} originals)"
    )
    return generation, manifest


def _restore_complete_generation(
    inputs: _DrillInputs,
    temporary: Path,
    generation: Path,
    manifest: object,
) -> None:
    from app.database import _database_generation_target_verification as target_verification
    from app.database import _dataset_restore_action as restore_action
    from app.services.dataset_restore_service import CompleteRestoreRequest
    from scripts.build_database_generation_program import write_program

    restored_originals = temporary / "restored-originals"
    restore_transport = make_url(inputs.restore_url)
    restore_hostaddr = restore_transport.query.get("hostaddr")
    if not isinstance(restore_hostaddr, str):
        raise SystemExit("FAIL drill: restore transport has no singular loopback hostaddr")
    managed_restore_url = restore_transport.set(
        host=restore_hostaddr,
        query={"require_auth": "scram-sha-256"},
    ).render_as_string(hide_password=False)
    program_path = temporary / "DATABASE_GENERATION_PROGRAM.json"
    program_sha256 = write_program(backend_root=BACKEND_ROOT, output=program_path)
    operation_id = str(uuid4())
    with managed_restore_role_topology(
        restore_url=inputs.restore_url,
        passfile=inputs.passfile,
    ) as schema_owner_role:
        restore_action.DATABASE_NAME = TEST_POSTGRES_CONTRACT.restore_database
        restore_action.MIGRATOR_ROLE = TEST_POSTGRES_CONTRACT.application_role
        restore_action.SCHEMA_OWNER_ROLE = schema_owner_role
        target_verification.LIVE_DATABASE = TEST_POSTGRES_CONTRACT.restore_database
        target_verification.MIGRATOR_ROLE = TEST_POSTGRES_CONTRACT.application_role
        target_verification.SCHEMA_OWNER_ROLE = schema_owner_role
        restored = restore_action.run_verified_isolated_dataset_restore_action(
            request=CompleteRestoreRequest(
                backup_generation=generation,
                target_upload_root=restored_originals,
                database_url=managed_restore_url,
                passfile=inputs.passfile,
                pg_restore_binary=inputs.pg_restore,
                active_installation_id=manifest.source_installation_id,
                active_dataset_id=manifest.authority.dataset_id,
                active_restore_epoch=manifest.authority.restore_epoch,
                target_schema_revision=manifest.authority.schema_revision,
                restore_role=schema_owner_role,
            ),
            generation_program_path=program_path,
            expected_generation_program_sha256=program_sha256,
            operation_id=operation_id,
        )
    if restored["backup_id"] != manifest.backup_id or restored["original_count"] != len(manifest.originals):
        raise SystemExit("FAIL drill: complete restore result differs from its generation")
    _assert_restored_originals(manifest, restored_originals)


def _writer_fence_sha256(authority: object, current_sha256: str) -> str:
    payload = {
        "schema": "ticketbox-dataset-backup-writer-barrier-v1",
        "current_sha256": current_sha256,
        "dataset_id": authority.dataset_id,
        "restore_epoch": authority.restore_epoch,
        "schema_revision": authority.schema_revision,
        "backend_service_state": "stopped",
        "other_client_session_count": 0,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def _assert_restored_originals(manifest: object, restored_originals: Path) -> None:
    from app.services.dataset_backup_contract import sha256_file

    actual = {
        path.relative_to(restored_originals).as_posix(): (path.stat().st_size, sha256_file(path))
        for path in restored_originals.rglob("*")
        if path.is_file() and not is_link_or_reparse(path)
    }
    expected = {
        Path(*Path(item.storage_key).parts[1:]).as_posix(): (item.size_bytes, item.sha256)
        for item in manifest.originals
    }
    if not expected or actual != expected:
        raise SystemExit("FAIL drill: restored original attachment set or bytes differ")
    print("OK complete isolated restore and exact original attachments")


def _assert_restored_database(
    source_facts: DatabaseFacts,
    restore_facts: DatabaseFacts,
    sanitation_tables: tuple[str, ...],
) -> None:
    preserved_tables = (
        set(source_facts.tables)
        - set(sanitation_tables)
        - {
            "app_meta",
            "dataset_authority",
        }
    )
    diffs = {
        table: (source_facts.tables.get(table), restore_facts.tables.get(table))
        for table in sorted(preserved_tables)
        if source_facts.tables.get(table) != restore_facts.tables.get(table)
    }
    unsanitized = {
        table: restore_facts.tables[table].row_count
        for table in sorted(set(sanitation_tables) & set(restore_facts.tables))
        if restore_facts.tables[table].row_count != 0
    }
    if (
        set(restore_facts.tables) != set(source_facts.tables)
        or restore_facts.sequences != source_facts.sequences
        or diffs
        or unsanitized
    ):
        missing = sorted(set(source_facts.tables) - set(restore_facts.tables))
        raise SystemExit(
            "FAIL drill: restored database contract differs "
            f"missing_tables={missing} preserved_diffs={diffs} unsanitized={unsanitized}"
        )
    print(
        f"OK restored data matches source: {len(restore_facts.tables)} tables, "
        f"{sum(item.row_count for item in restore_facts.tables.values())} rows "
        f"(incl. expenses={restore_facts.tables['expenses'].row_count})"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-root", type=Path, required=True)
    parser.add_argument("--frozen-restore-helper", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source_url = os.environ["DRILL_SOURCE_URL"]
    restore_url = os.environ["DRILL_RESTORE_URL"]
    passfile_value = os.environ.get("PGPASSFILE")
    if not passfile_value:
        raise SystemExit("FAIL drill: PGPASSFILE is required")
    try:
        passfile = Path(passfile_value).resolve(strict=True)
        upload_root = args.upload_root.resolve(strict=True)
        frozen_restore_helper = (
            args.frozen_restore_helper.resolve(strict=True) if args.frozen_restore_helper is not None else None
        )
    except OSError:
        raise SystemExit("FAIL drill: explicit passfile or upload root is unavailable") from None
    if not upload_root.is_dir() or is_link_or_reparse(upload_root):
        raise SystemExit("FAIL drill: upload root is not a plain directory")
    cluster_identity = os.environ["XPJ_TEST_CLUSTER_IDENTITY"]
    with (
        dedicated_test_database_lease(
            source_url,
            expected_database=TEST_POSTGRES_CONTRACT.smoke_database,
            reset=False,
            cluster_identity=cluster_identity,
            passfile=passfile,
        ) as source_connection,
        dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=cluster_identity,
            passfile=passfile,
        ),
    ):
        return _run_drill(
            source_url,
            restore_url,
            upload_root=upload_root,
            passfile=passfile,
            cluster_identity=cluster_identity,
            source_connection=source_connection,
            frozen_restore_helper=frozen_restore_helper,
        )


if __name__ == "__main__":
    raise SystemExit(main())
