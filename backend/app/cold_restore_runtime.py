"""One-shot entry of the existing frozen database-maintenance executable."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from app.database_maintenance_runtime import assert_maintenance_libpq_environment


def _payload(stream) -> dict:
    raw = stream.read(8193)
    if len(raw) > 8192:
        raise RuntimeError("restore identity input is too large")
    payload = json.loads(raw)
    if set(payload) != {"source", "installation_id", "backup_id", "operation_id", "bootstrap_secret", "recovery_secret"}:
        raise RuntimeError("restore identity input is not closed")
    source = payload["source"]
    for value in (payload["installation_id"], payload["backup_id"], source["install_id"], source["dataset_id"]):
        if str(UUID(value)) != value:
            raise RuntimeError("restore identity is not canonical")
    for secret in (payload["bootstrap_secret"], payload["recovery_secret"]):
        if not isinstance(secret, str) or not 32 <= len(secret) <= 256 or any(char.isspace() for char in secret):
            raise RuntimeError("restore credential input is invalid")
    if type(source["restore_epoch"]) is not int or source["restore_epoch"] < 0:
        raise RuntimeError("restore source epoch is invalid")
    return payload


def _verify_originals(db) -> int:
    from sqlalchemy import select

    from app.models import Expense, Ledger
    from app.services.file_service import resolve_upload_path_for_tenant
    from app.services.original_read_service import read_original_snapshot
    from app.services.original_reference_queries import referenced_upload_paths

    count = 0
    for expense in db.scalars(select(Expense).where(Expense.image_path.is_not(None), Expense.image_deleted_at.is_(None))):
        with read_original_snapshot(relative_path=expense.image_path, tenant_id=expense.tenant_id,
                expected_sha256=expense.image_hash):
            count += 1
    for ledger in db.scalars(select(Ledger)):
        for reference in referenced_upload_paths(db, ledger.ledger_id):
            path = resolve_upload_path_for_tenant(reference, ledger.ledger_id)
            if path is None or not path.is_file():
                raise RuntimeError("restore is missing a retained original reference")
    return count


def run_cold_restore(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--restore-cold-dataset", action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = _payload(sys.stdin.buffer)
    assert_maintenance_libpq_environment(args.pgpassfile)
    if not args.data_root.is_absolute():
        raise RuntimeError("restore data root must be explicit")
    os.environ["TICKETBOX_DATA_DIR"] = str(args.data_root / "app")
    os.environ["UPLOAD_DIR"] = str(args.data_root / "app" / "uploads")

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool

    from app.database._managed_postgres_contract import DATABASE_NAME, MIGRATOR_ROLE, SCHEMA_OWNER_ROLE
    from app.database._managed_postgres_role_authority import assume_managed_postgres_schema_owner
    from app.database._managed_postgres_url import validated_local_role_url
    from app.services.cold_restore_identity import rebind_cold_dataset
    from app.services.secure_file import hold_installer_machine_secret_for_read

    url = validated_local_role_url(args.database_url, database_name="ticketbox", role="ticketbox_migrator",
        purpose="cold restore")
    with hold_installer_machine_secret_for_read(args.pgpassfile):
        engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL statement_timeout = '120s'"))
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                assume_managed_postgres_schema_owner(connection, contract=SimpleNamespace(
                    database_name=DATABASE_NAME, migrator_role=MIGRATOR_ROLE, schema_owner_role=SCHEMA_OWNER_ROLE))
                revision = tuple(connection.scalars(text("SELECT version_num FROM alembic_version")))
                if revision != (payload["source"]["schema_revision"],):
                    raise RuntimeError("restore schema does not match the selected backup")
                with Session(bind=connection, expire_on_commit=False) as db:
                    originals = _verify_originals(db)
                    result = rebind_cold_dataset(db, **payload)
                    db.flush()
                    pairing = asdict(result)
        finally:
            engine.dispose()
    # The lifecycle coordinator receives this privately, just like Fresh pairing.
    print(json.dumps({"schema": "ticketbox-cold-restore-dataset-v1", "pairing": pairing,
        "dataset_id": payload["source"]["dataset_id"], "restore_epoch": payload["source"]["restore_epoch"] + 1,
        "installation_id": payload["installation_id"], "backup_id": payload["backup_id"],
        "verified_originals": originals}, ensure_ascii=True))
    return 0
