"""Exact frozen-EXE restore evidence against a disposable PostgreSQL topology."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from psycopg import Connection, sql
from sqlalchemy.engine import make_url

from app.services.dataset_backup_contract import DatasetBackupManifest
from app.services.secure_file import write_protected_file_exclusive
from scripts.postgres_dataset_facts import (
    DatabaseFacts,
    assert_database_fact_mutations_observed,
    read_database_facts,
)


def restore_with_frozen_helper(
    *,
    source_url: str,
    admin_url: str,
    admin_passfile: Path,
    helper: Path,
    pg_restore: Path,
    temporary: Path,
    generation: Path,
    manifest: DatasetBackupManifest,
) -> tuple[DatabaseFacts, Path]:
    """Run the shipped maintenance EXE with its exact program and role topology."""

    program = helper.parent / "DATABASE_GENERATION_PROGRAM.json"
    if helper.name.lower() != "ticketbox-database-maintenance.exe" or not program.is_file():
        raise SystemExit("FAIL drill: frozen restore shipment is incomplete")
    program_sha256 = hashlib.sha256(program.read_bytes()).hexdigest()
    parsed_source = make_url(source_url)
    if parsed_source.port is None:
        raise SystemExit("FAIL drill: source PostgreSQL port is absent")
    restored_originals = temporary / "frozen-restored-originals"
    with _frozen_restore_role_topology(
        temporary=temporary,
        port=parsed_source.port,
        admin_url=admin_url,
        admin_passfile=admin_passfile,
    ) as (restore_url, restore_passfile, admin_ticketbox_url):
        environment = {name: value for name, value in os.environ.items() if not name.upper().startswith("PG")}
        environment["PGPASSFILE"] = str(restore_passfile)
        completed = subprocess.run(
            [
                str(helper),
                "--isolated-dataset-restore",
                "--backup-generation",
                str(generation),
                "--target-upload-root",
                str(restored_originals),
                "--database-url",
                restore_url,
                "--pgpassfile",
                str(restore_passfile),
                "--pg-restore-path",
                str(pg_restore),
                "--active-installation-id",
                manifest.source_installation_id,
                "--active-dataset-id",
                manifest.authority.dataset_id,
                "--active-restore-epoch",
                str(manifest.authority.restore_epoch),
                "--target-schema-revision",
                manifest.authority.schema_revision,
                "--restore-role",
                "ticketbox_owner",
                "--generation-program-path",
                "DATABASE_GENERATION_PROGRAM.json",
                "--expected-generation-program-sha256",
                program_sha256,
                "--operation-id",
                str(uuid4()),
            ],
            input=b"",
            capture_output=True,
            cwd=helper.parent,
            env=environment,
            timeout=20 * 60,
        )
        if completed.returncode != 0 or completed.stderr:
            raise SystemExit("FAIL drill: frozen isolated restore helper rejected its exact shipment")
        try:
            result = json.loads(completed.stdout.decode("utf-8").strip())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit("FAIL drill: frozen restore result is invalid") from exc
        if (
            result.get("schema") != "ticketbox-isolated-dataset-restore-result-v2"
            or result.get("backup_id") != manifest.backup_id
            or result.get("result") != "isolated_restore_candidate_verified"
            or result.get("generation_program_sha256") != program_sha256
        ):
            raise SystemExit("FAIL drill: frozen restore result escaped its generation")
        restored_facts = read_database_facts(admin_ticketbox_url)
        assert_database_fact_mutations_observed(admin_ticketbox_url, restored_facts)
    print("OK exact frozen helper restored and verified the real PostgreSQL dataset")
    return restored_facts, restored_originals


@contextmanager
def _frozen_restore_role_topology(
    *,
    temporary: Path,
    port: int,
    admin_url: str,
    admin_passfile: Path,
) -> Iterator[tuple[str, Path, str]]:
    password = secrets.token_urlsafe(32)
    passfile = temporary / "frozen-restore.pgpass"
    write_protected_file_exclusive(
        passfile,
        f"127.0.0.1:{port}:ticketbox:ticketbox_migrator:{password}\n",
    )
    created_database = False
    created_roles: list[str] = []
    primary: BaseException | None = None
    cleanup: list[BaseException] = []
    try:
        with _admin_connection(admin_url, admin_passfile) as admin:
            if (
                admin.execute("SELECT datname FROM pg_catalog.pg_database WHERE datname = 'ticketbox'").fetchone()
                is not None
            ):
                raise RuntimeError("frozen restore test database already exists")
            for role in ("ticketbox_owner", "ticketbox_migrator"):
                if (
                    admin.execute(
                        "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
                        (role,),
                    ).fetchone()
                    is not None
                ):
                    raise RuntimeError("frozen restore test role already exists")
            admin.execute(
                "CREATE ROLE ticketbox_owner NOLOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            created_roles.append("ticketbox_owner")
            admin.execute(
                sql.SQL(
                    "CREATE ROLE ticketbox_migrator LOGIN NOINHERIT NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                    "CONNECTION LIMIT 1 PASSWORD {}"
                ).format(sql.Literal(password))
            )
            created_roles.append("ticketbox_migrator")
            admin.execute("GRANT ticketbox_owner TO ticketbox_migrator WITH INHERIT FALSE, SET TRUE")
            admin.execute("CREATE DATABASE ticketbox OWNER ticketbox_owner")
            created_database = True
            admin.execute("REVOKE CONNECT, CREATE, TEMPORARY ON DATABASE ticketbox FROM PUBLIC")
            admin.execute("GRANT CONNECT ON DATABASE ticketbox TO ticketbox_migrator")
        restore_url = f"postgresql+psycopg://ticketbox_migrator@127.0.0.1:{port}/ticketbox?require_auth=scram-sha-256"
        ticketbox_url = make_url(admin_url).set(database="ticketbox").render_as_string(hide_password=False)
        yield restore_url, passfile.resolve(strict=True), ticketbox_url
    except BaseException as exc:  # noqa: BLE001 - preserve drill failure
        primary = exc
    finally:
        try:
            with _admin_connection(admin_url, admin_passfile) as admin:
                if created_database:
                    admin.execute("DROP DATABASE ticketbox WITH (FORCE)")
                for role in reversed(created_roles):
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
            cleanup.append(exc)
        try:
            passfile.unlink(missing_ok=True)
        except BaseException as exc:  # noqa: BLE001 - preserve cleanup truth
            cleanup.append(exc)
    if primary is not None and cleanup:
        raise BaseExceptionGroup(
            "frozen restore drill and topology cleanup failed",
            [primary, *cleanup],
        ) from primary
    if primary is not None:
        raise primary
    if len(cleanup) == 1:
        raise cleanup[0]
    if cleanup:
        raise BaseExceptionGroup("frozen restore topology cleanup failed", cleanup)


def _admin_connection(admin_url: str, passfile: Path) -> Connection:
    return Connection.connect(
        admin_url.replace("+psycopg", ""),
        autocommit=True,
        passfile=str(passfile),
    )


__all__ = ["restore_with_frozen_helper"]
