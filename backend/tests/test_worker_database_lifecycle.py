from __future__ import annotations

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from tests._infra import env, worker_db


def _database_exists(
    connection: psycopg.Connection,
    database_name: str,
) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        == (1,)
    )


def _drop_test_databases(parsed: URL, *database_names: str) -> None:
    with worker_db._worker_lifecycle_guard(parsed) as connection:
        for database_name in database_names:
            worker_db._drop_database(connection, database_name)


def test_worker_lifecycle_reclaims_orphans_without_touching_live_leases() -> None:
    base_url = env.TEST_DATABASE_URL
    base_name = make_url(base_url).database
    assert base_name is not None
    stale_url = worker_db.worker_database_url(base_url, "gw7", "stale-run")
    unmarked_url = worker_db.worker_database_url(base_url, "gw6", "create-crash")
    first_url = worker_db.worker_database_url(base_url, "gw8", "first-run")
    second_url = worker_db.worker_database_url(base_url, "gw9", "second-run")
    stale_parsed = make_url(stale_url)
    unmarked_parsed = make_url(unmarked_url)
    first_parsed = make_url(first_url)
    second_parsed = make_url(second_url)
    stale_name = stale_parsed.database
    unmarked_name = unmarked_parsed.database
    first_name = first_parsed.database
    second_name = second_parsed.database
    assert stale_name is not None
    assert unmarked_name is not None
    assert first_name is not None
    assert second_name is not None
    database_names = (stale_name, unmarked_name, first_name, second_name)

    _drop_test_databases(stale_parsed, *database_names)
    with worker_db._worker_lifecycle_guard(stale_parsed) as connection:
        worker_db._create_worker_database(
            connection,
            database_name=stale_name,
            base_name=base_name,
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(unmarked_name))
        )

    try:
        with (
            worker_db.worker_database_lifecycle(
                first_url,
                worker_id="gw8",
                run_uid="first-run",
            ),
            worker_db.worker_database_lifecycle(
                second_url,
                worker_id="gw9",
                run_uid="second-run",
            ),
            worker_db._worker_lifecycle_guard(first_parsed) as connection,
        ):
            assert not _database_exists(connection, stale_name)
            assert not _database_exists(connection, unmarked_name)
            assert _database_exists(connection, first_name)
            assert _database_exists(connection, second_name)
    finally:
        _drop_test_databases(stale_parsed, *database_names)
