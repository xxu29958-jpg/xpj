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
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT  # noqa: E402
from scripts.test_postgres_database import dedicated_test_database_lease  # noqa: E402


class _BorrowedDbapiConnection:
    """Let SQLAlchemy use the leased DBAPI connection without owning it."""

    def __init__(self, connection: object) -> None:
        object.__setattr__(self, "_connection", connection)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._connection, name, value)

    def close(self) -> None:
        """The outer dedicated-database lease remains the connection owner."""


def _counts(url: str) -> dict[str, int]:
    """Row count per PUBLIC table — the whole schema, not a hand-kept list.

    Comparing every table catches a dump/restore that silently dropped a NEW
    table (the old fixed five-table list would have stayed green); comparing
    the table-name SETS catches a table that never came back at all.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
                )
            ]
            return {table: int(conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0) for table in tables}
    finally:
        engine.dispose()


def _run_drill(
    source_url: str,
    restore_url: str,
    *,
    upload_root: Path,
    passfile: Path,
    cluster_identity: str,
    source_connection: object,
) -> int:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.database import _dataset_restore_action as restore_action
    from app.services.backup_service import CompleteBackupRequest, create_complete_backup_generation
    from app.services.dataset_backup_contract import read_manifest, sha256_file
    from app.services.dataset_restore_service import _SANITATION_TABLES, CompleteRestoreRequest
    from app.services.postgres_backup_validation_service import find_pg_binary

    pg_dump = find_pg_binary("pg_dump", "PG_DUMP_PATH")
    pg_restore = find_pg_binary("pg_restore", "PG_RESTORE_PATH")
    if not pg_dump or not pg_restore:
        raise SystemExit("FAIL drill: supported PostgreSQL backup tools not found")

    source_counts = _counts(source_url)
    if source_counts["expenses"] == 0:
        raise SystemExit("FAIL drill: source has no expenses — did the smoke test run first?")

    borrowed_connection = _BorrowedDbapiConnection(source_connection)
    source_engine = create_engine(
        source_url,
        creator=lambda: borrowed_connection,
        poolclass=StaticPool,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="ticketbox-dataset-drill-") as temporary:
            backup_root = Path(temporary).resolve() / "backups"
            operation_id = str(uuid4())
            backup_id = str(uuid4())
            with Session(source_engine) as session:
                entry = create_complete_backup_generation(
                    CompleteBackupRequest(
                        backup_root=backup_root,
                        upload_root=upload_root,
                        database_url=source_url,
                        passfile=passfile,
                        pg_dump_binary=Path(pg_dump).resolve(strict=True),
                        pg_restore_binary=Path(pg_restore).resolve(strict=True),
                        operation_id=operation_id,
                        backup_id=backup_id,
                        release_id="ci-postgres-backup-drill",
                        backup_kind="manual",
                        writer_fence_sha256=hashlib.sha256(
                            f"test-only:dedicated-database-lease:{cluster_identity}".encode()
                        ).hexdigest(),
                    ),
                    db=session,
                )
            generation = backup_root / entry.file_name
            manifest = read_manifest(generation, verify_files=True)
            print(
                "OK complete dataset generation: "
                f"{entry.file_name} ({entry.size_bytes} bytes, {len(manifest.originals)} originals)"
            )
            restored_originals = Path(temporary).resolve() / "restored-originals"
            # This ephemeral lane has one purpose-built application role and
            # test database instead of the installed host's fixed role names.
            # Override only those policy constants; the complete production
            # action, transaction, sanitation, and filesystem code stay exact.
            restore_action.DATABASE_NAME = TEST_POSTGRES_CONTRACT.restore_database
            restore_action.MIGRATOR_ROLE = TEST_POSTGRES_CONTRACT.application_role
            restore_action.SCHEMA_OWNER_ROLE = TEST_POSTGRES_CONTRACT.application_role
            restored = restore_action.run_isolated_dataset_restore_action(
                CompleteRestoreRequest(
                    backup_generation=generation,
                    target_upload_root=restored_originals,
                    database_url=restore_url,
                    passfile=passfile,
                    pg_restore_binary=Path(pg_restore).resolve(strict=True),
                    active_dataset_id=manifest.authority.dataset_id,
                    active_restore_epoch=manifest.authority.restore_epoch,
                    target_schema_revision=manifest.authority.schema_revision,
                    restore_role=TEST_POSTGRES_CONTRACT.application_role,
                )
            )
            if restored["backup_id"] != manifest.backup_id or restored["original_count"] != len(manifest.originals):
                raise SystemExit("FAIL drill: complete restore result differs from its generation")
            actual_originals = {
                path.relative_to(restored_originals).as_posix(): (path.stat().st_size, sha256_file(path))
                for path in restored_originals.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
            expected_originals = {
                Path(*Path(item.storage_key).parts[1:]).as_posix(): (item.size_bytes, item.sha256)
                for item in manifest.originals
            }
            if not expected_originals or actual_originals != expected_originals:
                raise SystemExit("FAIL drill: restored original attachment set or bytes differ")
            print("OK complete isolated restore and exact original attachments")
    finally:
        # The wrapper makes close a no-op; the outer lease releases its advisory
        # lock and closes the raw connection after this function returns.
        source_engine.dispose()

    restore_counts = _counts(restore_url)
    preserved_tables = set(source_counts) - set(_SANITATION_TABLES) - {
        "app_meta",
        "dataset_authority",
    }
    diffs = {
        table: (source_counts.get(table), restore_counts.get(table))
        for table in sorted(preserved_tables)
        if source_counts.get(table) != restore_counts.get(table)
    }
    unsanitized = {
        table: restore_counts.get(table)
        for table in sorted(set(_SANITATION_TABLES) & set(restore_counts))
        if restore_counts.get(table) != 0
    }
    if set(restore_counts) != set(source_counts) or diffs or unsanitized:
        missing = sorted(set(source_counts) - set(restore_counts))
        raise SystemExit(
            "FAIL drill: restored database contract differs "
            f"missing_tables={missing} preserved_diffs={diffs} unsanitized={unsanitized}"
        )
    print(
        f"OK restored data matches source: {len(restore_counts)} tables, "
        f"{sum(restore_counts.values())} rows (incl. expenses={restore_counts.get('expenses', 0)})"
    )

    print("\nPASS postgres backup/restore drill")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-root", type=Path, required=True)
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
    except OSError:
        raise SystemExit("FAIL drill: explicit passfile or upload root is unavailable") from None
    if not upload_root.is_dir() or upload_root.is_symlink():
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
        )


if __name__ == "__main__":
    raise SystemExit(main())
