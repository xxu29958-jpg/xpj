"""PostgreSQL 17 behavior proof for the Windows C07 database authority SQL."""

from __future__ import annotations

import shutil
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from tests._infra.env import ADMIN_TEST_DATABASE_URL

pytestmark = pytest.mark.real_db


def _conninfo(
    *,
    database: str,
    username: str | None = None,
    password: str | None = None,
) -> str:
    url = make_url(ADMIN_TEST_DATABASE_URL).set(
        drivername="postgresql",
        database=database,
    )
    if username is not None:
        url = url.set(username=username, password=password)
    return url.render_as_string(hide_password=False)


def _close(connection: psycopg.Connection | None) -> None:
    if connection is not None:
        with suppress(Exception):
            connection.close()

def test_pg17_transaction_timeout_must_be_armed_before_begin_and_rolls_back() -> None:
    table = f"c07_timeout_probe_{uuid4().hex[:16]}"
    test_database = make_url(ADMIN_TEST_DATABASE_URL).database
    assert test_database is not None
    admin_url = _conninfo(database=test_database)
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        server_version = int(admin.execute("SHOW server_version_num").fetchone()[0])
        assert server_version >= 170000
        admin.execute(
            sql.SQL("CREATE TABLE {} (probe integer PRIMARY KEY)").format(
                sql.Identifier(table)
            )
        )

        old_design = psycopg.connect(admin_url, autocommit=True)
        try:
            old_design.execute("SET statement_timeout = 0")
            old_design.execute("SET idle_in_transaction_session_timeout = 0")
            old_design.execute("SET transaction_timeout = '5s'")
            old_design.execute("BEGIN")
            old_design.execute("SET transaction_timeout = '1s'")
            started = time.monotonic()
            old_design.execute("SELECT pg_sleep(1.25)")
            assert time.monotonic() - started >= 1.0
            old_design.execute("ROLLBACK")
        finally:
            _close(old_design)

        prearmed = psycopg.connect(admin_url, autocommit=True)
        try:
            prearmed.execute("SET statement_timeout = 0")
            prearmed.execute("SET idle_in_transaction_session_timeout = 0")
            prearmed.execute("SET transaction_timeout = '1s'")
            prearmed.execute("BEGIN")
            prearmed.execute(
                sql.SQL("INSERT INTO {} (probe) VALUES (1)").format(
                    sql.Identifier(table)
                )
            )
            started = time.monotonic()
            with pytest.raises(psycopg.errors.TransactionTimeout) as exc_info:
                prearmed.execute("SELECT pg_sleep(5)")
            assert exc_info.value.sqlstate == "25P04"
            elapsed = time.monotonic() - started
            assert 0.65 <= elapsed < 4.0
        finally:
            _close(prearmed)

        persisted = admin.execute(
            sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        ).fetchone()[0]
        assert persisted == 0
    finally:
        with suppress(Exception):
            admin.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table))
            )
        admin.close()


def test_pg17_no_owner_restore_requires_the_exact_object_owner_role(
    tmp_path: Path,
) -> None:
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    assert pg_dump is not None
    assert pg_restore is not None
    suffix = uuid4().hex[:12]
    table = f"generation_restore_{suffix}"
    owner = f"generation_owner_{suffix}"
    wrong_owner = f"generation_wrong_{suffix}"
    exact_database = f"generation_exact_{suffix}"
    wrong_database = f"generation_wrong_{suffix}"
    source_database = make_url(ADMIN_TEST_DATABASE_URL).database
    assert source_database is not None
    source_url = _conninfo(database=source_database)
    postgres_url = _conninfo(database="postgres")
    admin = psycopg.connect(postgres_url, autocommit=True)
    source = psycopg.connect(source_url, autocommit=True)
    archive = tmp_path / "generation-role.dump"
    try:
        for role in (owner, wrong_owner):
            admin.execute(
                sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role))
            )
        source.execute(
            sql.SQL("CREATE TABLE {} (probe integer PRIMARY KEY)").format(
                sql.Identifier(table)
            )
        )
        source.execute(
            sql.SQL("INSERT INTO {} (probe) VALUES (1)").format(
                sql.Identifier(table)
            )
        )
        subprocess.run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--file",
                str(archive),
                "--table",
                f"public.{table}",
                source_url,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        for database in (exact_database, wrong_database):
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(database)
                )
            )
            target = psycopg.connect(_conninfo(database=database), autocommit=True)
            try:
                target.execute(
                    sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                        sql.Identifier(owner)
                    )
                )
            finally:
                target.close()
        exact = subprocess.run(
            [
                pg_restore,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                f"--role={owner}",
                "--dbname",
                _conninfo(database=exact_database),
                str(archive),
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
        assert exact.returncode == 0, exact.stderr.decode(errors="replace")
        wrong = subprocess.run(
            [
                pg_restore,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                f"--role={wrong_owner}",
                "--dbname",
                _conninfo(database=wrong_database),
                str(archive),
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
        assert wrong.returncode != 0
        exact_target = psycopg.connect(
            _conninfo(database=exact_database), autocommit=True
        )
        try:
            observed_owner = exact_target.execute(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = %s",
                (table,),
            ).fetchone()[0]
            assert observed_owner == owner
        finally:
            exact_target.close()
    finally:
        with suppress(psycopg.Error):
            source.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table))
            )
        source.close()
        for database in (exact_database, wrong_database):
            with suppress(psycopg.Error):
                admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )
        for role in (wrong_owner, owner):
            with suppress(psycopg.Error):
                admin.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                )
        admin.close()
