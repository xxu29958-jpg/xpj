"""PostgreSQL 17 behavior proof for the Windows C07 database authority SQL."""

from __future__ import annotations

import time
from contextlib import suppress
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
