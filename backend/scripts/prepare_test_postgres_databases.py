"""Create and verify the isolated databases required by one CI lane."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import psycopg
from psycopg import pq, sql

from scripts.postgres_release_policy import POSTGRES_RELEASE_POLICY
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import validated_test_postgres_conninfo

_ROLE_DATABASES = {
    "base": TEST_POSTGRES_CONTRACT.base_database,
    "smoke": TEST_POSTGRES_CONTRACT.smoke_database,
    "restore": TEST_POSTGRES_CONTRACT.restore_database,
}
_ROLE_URLS = {
    "base": "XPJ_TEST_DATABASE_URL",
    "smoke": "SMOKE_DATABASE_URL",
    "restore": "DRILL_RESTORE_URL",
}


def _application_credential() -> tuple[str, str]:
    if pq.version() < 170000:
        raise RuntimeError("test PostgreSQL clients must support require_auth")
    application_role = TEST_POSTGRES_CONTRACT.application_role
    application_password = os.environ.get("XPJ_TEST_APPLICATION_PASSWORD")
    if not application_password or "\n" in application_password or "\r" in application_password:
        raise RuntimeError("test PostgreSQL application credential is unavailable")
    return application_role, application_password


def _cluster_identity() -> str:
    return TEST_POSTGRES_CONTRACT.require_database_identity(
        os.environ.get("XPJ_TEST_CLUSTER_IDENTITY")
    )


def _server_version(
    connection: psycopg.Connection,
    *,
    expected_major: int,
) -> tuple[int, int, int]:
    version_row = connection.execute("SELECT current_setting('server_version_num')").fetchone()
    if version_row is None or len(version_row) != 1:
        raise RuntimeError("cannot read PostgreSQL server_version_num")
    return POSTGRES_RELEASE_POLICY.verify_server_version(
        version_row[0],
        expected_major=expected_major,
    )


def _create_application_databases(
    connection: psycopg.Connection,
    *,
    roles: Sequence[str],
    application_role: str,
    application_password: str,
    cluster_identity: str,
) -> None:
    existing_role = connection.execute(
        "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
        (application_role,),
    ).fetchone()
    if existing_role is not None:
        raise RuntimeError(f"test PostgreSQL application role already exists: {application_role}")
    connection.execute("SET password_encryption = 'scram-sha-256'")
    connection.execute(
        sql.SQL(
            "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "INHERIT NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(
            sql.Identifier(application_role),
            sql.Literal(application_password),
        )
    )
    for role in roles:
        database = _ROLE_DATABASES[role]
        exists = connection.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (database,),
        ).fetchone()
        if exists is not None:
            raise RuntimeError(f"test PostgreSQL database already exists: {database}")
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database),
                sql.Identifier(application_role),
            )
        )
        connection.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(database),
                sql.Literal(cluster_identity),
            )
        )


def _verify_application_databases(
    roles: Sequence[str],
    *,
    application_role: str,
    cluster_identity: str,
) -> None:
    for role in roles:
        expected_database = _ROLE_DATABASES[role]
        url = validated_test_postgres_conninfo(
            os.environ[_ROLE_URLS[role]],
            expected_database=expected_database,
            expected_user=application_role,
        )
        with psycopg.connect(url) as connection:
            actual_database, actual_user, is_superuser, is_owner, database_identity = connection.execute(
                """
                SELECT current_database(), current_user,
                       current_setting('is_superuser')::boolean,
                       pg_catalog.pg_get_userbyid(datdba) = current_user,
                       pg_catalog.shobj_description(oid, 'pg_database')
                FROM pg_catalog.pg_database
                WHERE datname = current_database()
                """
            ).fetchone()
        if (
            actual_database != expected_database
            or actual_user != application_role
            or is_superuser
            or not is_owner
            or database_identity != cluster_identity
        ):
            raise RuntimeError(f"test PostgreSQL role {role} did not match the application authority")


def prepare_databases(roles: Sequence[str], *, expected_major: int) -> None:
    application_role, application_password = _application_credential()
    cluster_identity = _cluster_identity()
    admin_url = validated_test_postgres_conninfo(
        os.environ["XPJ_TEST_ADMIN_URL"],
        expected_database="postgres",
        expected_user="postgres",
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        server_version = _server_version(
            connection,
            expected_major=expected_major,
        )
        _create_application_databases(
            connection,
            roles=roles,
            application_role=application_role,
            application_password=application_password,
            cluster_identity=cluster_identity,
        )
    _verify_application_databases(
        roles,
        application_role=application_role,
        cluster_identity=cluster_identity,
    )
    print("Verified PostgreSQL server version: " + ".".join(map(str, server_version)))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role",
        action="append",
        choices=tuple(_ROLE_DATABASES),
        dest="roles",
        required=True,
    )
    parser.add_argument("--expected-major", type=int, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if len(set(args.roles)) != len(args.roles):
        raise RuntimeError("test PostgreSQL roles must be unique")
    prepare_databases(args.roles, expected_major=args.expected_major)
    print(f"Prepared test PostgreSQL roles: {', '.join(args.roles)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
