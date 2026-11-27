"""One-shot entry of the existing frozen database-maintenance executable."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from app.database_maintenance_runtime import (
    DatabaseMaintenanceContractError,
    assert_maintenance_libpq_environment,
    standalone_database_package,
)


def _payload(stream) -> dict:
    raw = stream.read(8193)
    if len(raw) > 8192:
        raise DatabaseMaintenanceContractError("restore identity input is too large")
    payload = json.loads(raw)
    if set(payload) != {"source", "installation_id", "backup_id", "operation_id", "bootstrap_secret", "recovery_secret"}:
        raise DatabaseMaintenanceContractError("restore identity input is not closed")
    source = payload["source"]
    for value in (payload["installation_id"], payload["backup_id"], source["install_id"], source["dataset_id"]):
        if str(UUID(value)) != value:
            raise DatabaseMaintenanceContractError("restore identity is not canonical")
    for secret in (payload["bootstrap_secret"], payload["recovery_secret"]):
        if not isinstance(secret, str) or not 32 <= len(secret) <= 256 or any(char.isspace() for char in secret):
            raise DatabaseMaintenanceContractError("restore credential input is invalid")
    if type(source["restore_epoch"]) is not int or source["restore_epoch"] < 0:
        raise DatabaseMaintenanceContractError("restore source epoch is invalid")
    return payload


def _verify_single_original(check, *, upload_root: Path) -> int:
    from app.errors import AppError
    from app.services.original_read_service import read_original_snapshot_in_root, recorded_original_digest
    from app.services.upload_path_resolver import resolve_upload_path_for_tenant_in_root

    if check.require_digest and recorded_original_digest(check.expected_sha256) is None:
        raise DatabaseMaintenanceContractError(
            f"restore retained original ({check.source_kind}) lacks a valid sha256 digest"
        )
    needs_snapshot = (
        check.source_kind in {"expense_image", "debt_bill_capture", "historical_original"}
        or bool(check.expected_sha256)
    )
    if not needs_snapshot:
        path = resolve_upload_path_for_tenant_in_root(
            check.relative_path,
            check.tenant_id,
            upload_root=upload_root,
        )
        if path is None or not path.is_file():
            raise DatabaseMaintenanceContractError(
                f"restore is missing a retained original reference ({check.source_kind})"
            )
        return 0
    try:
        with read_original_snapshot_in_root(
            relative_path=check.relative_path,
            tenant_id=check.tenant_id,
            expected_sha256=check.expected_sha256,
            upload_root=upload_root,
        ) as snapshot:
            if check.expected_size_bytes is not None and snapshot.size_bytes != check.expected_size_bytes:
                raise DatabaseMaintenanceContractError(
                    f"restore retained original ({check.source_kind}) size mismatch"
                )
    except AppError as exc:
        raise DatabaseMaintenanceContractError(
            f"restore retained original verification failed ({check.source_kind}): {exc.error}"
        ) from exc
    return 1


def _verify_originals(db, *, upload_root: Path) -> int:
    from sqlalchemy import select

    from app.models import Ledger
    from app.services.original_reference_queries import iter_retained_original_checks_in_root

    count = 0
    for ledger in db.scalars(select(Ledger)):
        try:
            checks = iter_retained_original_checks_in_root(
                db,
                ledger.ledger_id,
                upload_root=upload_root,
            )
        except ValueError as exc:
            raise DatabaseMaintenanceContractError(str(exc)) from exc
        for check in checks:
            count += _verify_single_original(check, upload_root=upload_root)
    return count


def _execute_cold_restore_transaction(
    connection,
    payload: dict,
    *,
    upload_root: Path,
    database_name: str,
    migrator_role: str,
    schema_owner_role: str,
) -> tuple[dict, int, dict[str, int]]:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.database._managed_postgres_role_authority import assume_managed_postgres_schema_owner
    from app.database._release_schema_readiness import assert_release_head
    from app.database._runtime_authority_privileges import seal_upgrade_attestation_guard
    from app.services.cold_restore_identity import rebind_cold_dataset_with_summary

    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    assume_managed_postgres_schema_owner(
        connection,
        contract=SimpleNamespace(
            database_name=database_name,
            migrator_role=migrator_role,
            schema_owner_role=schema_owner_role,
        ),
    )
    assert_release_head(connection, expected_revision=payload["source"]["schema_revision"])
    with Session(bind=connection, expire_on_commit=False) as db:
        originals = _verify_originals(db, upload_root=upload_root)
        result, revoked_summary = rebind_cold_dataset_with_summary(db, **payload)
        db.flush()
        pairing = asdict(result)
    if not seal_upgrade_attestation_guard(connection, owner_role=schema_owner_role):
        raise DatabaseMaintenanceContractError("upgrade attestation guard could not be sealed")
    return pairing, originals, revoked_summary


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
        raise DatabaseMaintenanceContractError("restore data root must be explicit")
    upload_root = (args.data_root / "app" / "uploads").resolve()

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from app.services.secure_file import hold_installer_machine_secret_for_read

    with standalone_database_package():
        from app.database._managed_postgres_contract import DATABASE_NAME, MIGRATOR_ROLE, SCHEMA_OWNER_ROLE
        from app.database._managed_postgres_url import validated_local_role_url

        url = validated_local_role_url(args.database_url, database_name="ticketbox", role="ticketbox_migrator",
            purpose="cold restore")
        with hold_installer_machine_secret_for_read(args.pgpassfile):
            engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
            try:
                with engine.begin() as connection:
                    pairing, originals, revoked_summary = _execute_cold_restore_transaction(
                        connection,
                        payload,
                        upload_root=upload_root,
                        database_name=DATABASE_NAME,
                        migrator_role=MIGRATOR_ROLE,
                        schema_owner_role=SCHEMA_OWNER_ROLE,
                    )
            finally:
                engine.dispose()
    print(json.dumps({"schema": "ticketbox-cold-restore-dataset-v1", "pairing": pairing,
        "dataset_id": payload["source"]["dataset_id"], "restore_epoch": payload["source"]["restore_epoch"] + 1,
        "installation_id": payload["installation_id"], "backup_id": payload["backup_id"],
        "verified_originals": originals, "revoked_credentials_summary": revoked_summary}, ensure_ascii=True))
    return 0


def _verify_preserved_dataset_transaction(
    connection,
    *,
    upload_root: Path,
    dataset_id: str,
    installation_id: str,
    expected_restore_epoch: int,
    schema_revision: str,
    semantic_revision: str,
    database_name: str,
    migrator_role: str,
    schema_owner_role: str,
) -> dict[str, object]:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from app.database._managed_postgres_role_authority import assume_managed_postgres_schema_owner
    from app.database._release_schema_readiness import assert_release_head
    from app.models import DatasetAuthorityRecord

    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout = '120s'"))
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    assume_managed_postgres_schema_owner(
        connection,
        contract=SimpleNamespace(
            database_name=database_name,
            migrator_role=migrator_role,
            schema_owner_role=schema_owner_role,
        ),
    )
    assert_release_head(connection, expected_revision=schema_revision)
    with Session(bind=connection, expire_on_commit=False) as db:
        authority = db.get(DatasetAuthorityRecord, 1)
        if authority is None:
            raise DatabaseMaintenanceContractError("preserved dataset authority row is missing")
        if (
            authority.dataset_id != dataset_id
            or authority.client_generation != installation_id
            or authority.restore_epoch != expected_restore_epoch
            or authority.schema_revision != schema_revision
            or authority.semantic_revision != semantic_revision
        ):
            raise DatabaseMaintenanceContractError("preserved dataset authority does not match installation binding")
        originals = _verify_originals(db, upload_root=upload_root)
    return {
        "schema": "ticketbox-preserved-dataset-verify-v1",
        "dataset_id": dataset_id,
        "installation_id": installation_id,
        "restore_epoch": expected_restore_epoch,
        "schema_revision": schema_revision,
        "semantic_revision": semantic_revision,
        "verified_originals": originals,
    }


def run_verify_preserved_dataset(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--verify-preserved-dataset", action="store_true", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--pgpassfile", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--expected-restore-epoch", type=int, required=True)
    parser.add_argument("--schema-revision", required=True)
    parser.add_argument("--semantic-revision", required=True)
    args = parser.parse_args(argv)
    if sys.stdin.buffer.read(1) != b"":
        raise DatabaseMaintenanceContractError("preserved dataset verification requires empty stdin")
    assert_maintenance_libpq_environment(args.pgpassfile)
    if not args.data_root.is_absolute():
        raise DatabaseMaintenanceContractError("data root must be explicit")
    for value in (args.dataset_id, args.installation_id):
        if str(UUID(value)) != value:
            raise DatabaseMaintenanceContractError("dataset identity is not canonical")
    if args.expected_restore_epoch < 0:
        raise DatabaseMaintenanceContractError("restore epoch is invalid")
    upload_root = (args.data_root / "app" / "uploads").resolve()

    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    from app.services.secure_file import hold_installer_machine_secret_for_read

    with standalone_database_package():
        from app.database._managed_postgres_contract import DATABASE_NAME, MIGRATOR_ROLE, SCHEMA_OWNER_ROLE
        from app.database._managed_postgres_url import validated_local_role_url

        url = validated_local_role_url(
            args.database_url,
            database_name="ticketbox",
            role="ticketbox_migrator",
            purpose="preserved dataset verification",
        )
        with hold_installer_machine_secret_for_read(args.pgpassfile):
            engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 10})
            try:
                with engine.begin() as connection:
                    result = _verify_preserved_dataset_transaction(
                        connection,
                        upload_root=upload_root,
                        dataset_id=args.dataset_id,
                        installation_id=args.installation_id,
                        expected_restore_epoch=args.expected_restore_epoch,
                        schema_revision=args.schema_revision,
                        semantic_revision=args.semantic_revision,
                        database_name=DATABASE_NAME,
                        migrator_role=MIGRATOR_ROLE,
                        schema_owner_role=SCHEMA_OWNER_ROLE,
                    )
            finally:
                engine.dispose()
    print(json.dumps(result, ensure_ascii=True))
    return 0
