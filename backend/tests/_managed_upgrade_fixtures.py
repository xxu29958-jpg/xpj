"""Shared real-PostgreSQL topology and cold-copy-v2 archive builders for managed upgrade tests."""

from __future__ import annotations

import hashlib
import json
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.database._database_generation_executor import UPGRADE_ATTESTATION_META_KEY
from app.services.secure_file import write_protected_file_exclusive
from tests._infra.alembic_runtime import alembic_config_for_test, run_alembic_for_test
from tests._infra.postgres_topology_cleanup import cleanup_postgres_topology
from tests.managed_postgres_test_support import (
    _MIGRATOR_PASSWORD,
    _create_roles_and_database,
    _new_managed_topology,
)

_PREV_REVISION = "20261029_0002"
_HEAD_REVISION = "20261101_0001"
_INSTALL_ID = "11111111-1111-4111-8111-111111111111"
_DATASET_ID = "22222222-2222-4222-8222-222222222222"
_BACKUP_ID = "33333333-3333-4333-8333-333333333333"


@contextmanager
def _upgrade_topology(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_revision: str,
    restore_epoch: int = 0,
):
    topology = _new_managed_topology(tmp_path)
    try:
        _create_roles_and_database(topology)
        owner_engine = create_engine(topology.owner_url, poolclass=NullPool, future=True)
        try:
            run_alembic_for_test(
                owner_engine,
                alembic_config_for_test(),
                command.upgrade,
                initial_revision,
            )
            with owner_engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE public.dataset_authority SET "
                        "dataset_id = :dataset_id, client_generation = :install_id, "
                        "restore_epoch = :restore_epoch, restored_from_backup_id = :backup_id "
                        "WHERE singleton_id = 1"
                    ),
                    {
                        "dataset_id": _DATASET_ID,
                        "install_id": _INSTALL_ID,
                        "restore_epoch": restore_epoch,
                        "backup_id": _BACKUP_ID if restore_epoch > 0 else None,
                    },
                )
        finally:
            owner_engine.dispose()
        topology.admin.execute(
            sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(topology.owner))
        )
        write_protected_file_exclusive(
            topology.pgpass,
            (
                f"127.0.0.1:{topology.migrator_url.port}:"
                f"{topology.database}:{topology.migrator}:{_MIGRATOR_PASSWORD}\n"
            ),
        )
        monkeypatch.delenv("PGPASSWORD", raising=False)
        yield topology
    finally:
        cleanup_postgres_topology(
            admin=topology.admin,
            database=topology.database,
            roles=(topology.runtime_role, topology.migrator, topology.owner),
        )


def _read_attestation(url) -> dict[str, object] | None:
    engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            raw = conn.scalar(
                text("SELECT value FROM public.app_meta WHERE key = :key"),
                {"key": UPGRADE_ATTESTATION_META_KEY},
            )
            return None if raw is None else json.loads(str(raw))
    finally:
        engine.dispose()


def _write_valid_cold_copy_v2(
    archive_path: Path,
    *,
    dataset_id: str,
    installation_id: str,
    restore_epoch: int,
    source_revision: str,
    release_id: str = "1.2.1",
    extra_members: dict[str, bytes] | None = None,
    extra_index_only: dict[str, dict[str, object]] | None = None,
    omit_member: str | None = None,
    include_program_inventory: bool = True,
    corrupt_member_bytes: dict[str, bytes] | None = None,
    app_dir_for_pg: Path | None = None,
) -> str:
    program_files: dict[str, bytes] = {
        "postgresql/bin/postgres.exe": b"pg-17-binary-fixture",
        f"releases/{release_id}/backend/ticketbox-backend.exe": b"backend-binary-fixture",
        "bin/lifecycle/TicketboxLifecycle.exe": b"lifecycle-binary-fixture",
    }
    if app_dir_for_pg is not None:
        pg_bin = app_dir_for_pg / "postgresql" / "bin" / "postgres.exe"
        pg_bin.parent.mkdir(parents=True, exist_ok=True)
        pg_bin.write_bytes(program_files["postgresql/bin/postgres.exe"])
    manifest_payload: dict[str, object] = {
        "schema": "ticketbox-release-manifest-v1",
        "release_id": release_id,
        "product_version": release_id,
        "max_schema_revision": source_revision,
        "min_semantic_revision": "ticketbox-dataset-semantics-v1",
    }
    if include_program_inventory:
        manifest_payload["immutable_payload"] = {
            "files": [
                {
                    "path": rel,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for rel, data in sorted(program_files.items())
            ]
        }
    manifest_bytes = json.dumps(manifest_payload).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    origin_op = f"fresh-{manifest_sha}"
    members: dict[str, bytes] = {
        "data/pgdata/PG_VERSION": b"17\n",
        "data/pgdata/global/pg_control": b"clean-pg-control",
        "data/app/.env": b"SECRET=1\n",
        "machine/installation.json": json.dumps({
            "schema": "ticketbox-installed-instance-v1",
            "install_id": installation_id,
            "dataset_id": dataset_id,
            "expected_restore_epoch": restore_epoch,
            "active_release_id": release_id,
            "previous_release_id": None,
            "release_manifest_sha256": manifest_sha,
        }).encode("utf-8"),
        "machine/secrets/postgres.password": b"fixture-pg-secret",
        "machine/secrets/ticketbox_migrator.password": b"fixture-migrator-secret",
        "machine/secrets/ticketbox_runtime.password": b"fixture-runtime-secret",
        "machine/secrets/pgpass": b"127.0.0.1:5438:*:ticketbox_migrator:secret\n",
        f"program/releases/{release_id}/release-manifest.json": manifest_bytes,
        f"machine/operations/history/{origin_op}.json": json.dumps({
            "schema": "ticketbox-lifecycle-operation-v2",
            "operation_id": origin_op,
            "kind": "install",
            "target_release_id": release_id,
            "release_manifest_sha256": manifest_sha,
            "phase": "committed",
            "install_id": installation_id,
            "dataset_id": dataset_id,
        }).encode("utf-8"),
    }
    if include_program_inventory:
        for rel, data in program_files.items():
            members["program/" + rel] = data
    if extra_members:
        members.update(extra_members)
    if omit_member:
        members.pop(omit_member, None)
    dirs = (
        "program/",
        "program/postgresql/",
        "program/postgresql/bin/",
        "program/bin/",
        "program/bin/lifecycle/",
        "program/releases/",
        f"program/releases/{release_id}/",
        f"program/releases/{release_id}/backend/",
        "machine/",
        "machine/secrets/",
        "machine/operations/",
        "machine/operations/history/",
        "data/pgdata/",
        "data/pgdata/global/",
        "data/attachments/",
        "data/app/",
    )
    entries: dict[str, object] = dict.fromkeys(dirs, None)
    for name, payload in sorted(members.items()):
        entries[name] = {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    if extra_index_only:
        entries.update(extra_index_only)
    cold_manifest = {
        "schema": "ticketbox-beta-cold-copy-v2",
        "complete": True,
        "identity": {
            "install_id": installation_id,
            "dataset_id": dataset_id,
            "restore_epoch": restore_epoch,
            "release_id": release_id,
            "release_manifest_sha256": manifest_sha,
            "schema_revision": source_revision,
            "postgres_major": 17,
            "postgres_system_identifier": "123456789",
        },
        "entries": entries,
        "public_connectivity": {
            "excluded_directory": "machine/connectors/cloudflare/secrets",
            "credentials": "not_backed_up",
            "after_restore": "configure_again",
        },
    }
    with zipfile.ZipFile(archive_path, "w") as zf:
        for d in dirs:
            zf.writestr(d, b"")
        for name, payload in sorted(members.items()):
            actual_bytes = (
                corrupt_member_bytes[name]
                if corrupt_member_bytes and name in corrupt_member_bytes
                else payload
            )
            zf.writestr(name, actual_bytes)
        zf.writestr("COLD_COPY.json", json.dumps(cold_manifest))
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


