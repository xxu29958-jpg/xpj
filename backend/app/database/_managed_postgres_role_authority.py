"""Exact PostgreSQL role authority checks for database maintenance."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Connection


class ManagedPostgresRoleContract(Protocol):
    database_name: str
    migrator_role: str
    schema_owner_role: str


class ManagedPostgresRoleAuthorityError(RuntimeError):
    """The maintenance connection cannot prove its bounded role authority."""


def _assert_migrator_principal(
    connection: Connection,
    contract: ManagedPostgresRoleContract,
) -> None:
    principal = tuple(
        str(value)
        for value in connection.execute(
            text("SELECT session_user, current_user, current_database()")
        ).one()
    )
    expected = (
        contract.migrator_role,
        contract.migrator_role,
        contract.database_name,
    )
    if principal != expected:
        raise ManagedPostgresRoleAuthorityError(
            "managed migration connection is not the dedicated migrator"
        )


def _assert_role_attributes(
    connection: Connection,
    contract: ManagedPostgresRoleContract,
) -> None:
    rows = tuple(
        connection.execute(
            text(
                "SELECT rolname, rolcanlogin, rolinherit, rolsuper, "
                "rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                "FROM pg_catalog.pg_roles WHERE rolname IN "
                "(:owner, :migrator) ORDER BY rolname"
            ),
            {"owner": contract.schema_owner_role, "migrator": contract.migrator_role},
        ).all()
    )
    roles = {str(row[0]): tuple(row[1:]) for row in rows}
    expected = {
        contract.migrator_role: (True, False, False, False, False, False, False),
        contract.schema_owner_role: (False, False, False, False, False, False, False),
    }
    if len(rows) != 2 or roles != expected:
        raise ManagedPostgresRoleAuthorityError(
            "managed migration owner/migrator role attributes are not exact"
        )


def _assert_role_membership(
    connection: Connection,
    contract: ManagedPostgresRoleContract,
) -> None:
    membership = tuple(
        connection.execute(
            text(
                "SELECT granted.rolname, member.rolname, membership.admin_option, "
                "membership.inherit_option, membership.set_option "
                "FROM pg_catalog.pg_auth_members AS membership "
                "JOIN pg_catalog.pg_roles AS granted ON granted.oid = membership.roleid "
                "JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member "
                "WHERE granted.rolname IN (:owner, :migrator) "
                "OR member.rolname IN (:owner, :migrator)"
            ),
            {"owner": contract.schema_owner_role, "migrator": contract.migrator_role},
        ).all()
    )
    expected = ((contract.schema_owner_role, contract.migrator_role, False, False, True),)
    if membership != expected:
        raise ManagedPostgresRoleAuthorityError(
            "managed migration owner/migrator membership is not exact"
        )


def _assume_schema_owner(
    connection: Connection,
    contract: ManagedPostgresRoleContract,
) -> None:
    owner = connection.dialect.identifier_preparer.quote_identifier(
        contract.schema_owner_role
    )
    connection.execute(text(f"SET LOCAL ROLE {owner}"))
    effective = tuple(
        str(value)
        for value in connection.execute(text("SELECT session_user, current_user")).one()
    )
    if effective != (contract.migrator_role, contract.schema_owner_role):
        raise ManagedPostgresRoleAuthorityError(
            "managed migrator cannot assume the schema owner"
        )


def _assert_database_and_schema_owners(
    connection: Connection,
    contract: ManagedPostgresRoleContract,
) -> None:
    owners = connection.execute(
        text(
            "SELECT pg_get_userbyid(database_record.datdba), "
            "pg_get_userbyid(namespace_record.nspowner) "
            "FROM pg_catalog.pg_database AS database_record "
            "JOIN pg_catalog.pg_namespace AS namespace_record "
            "ON namespace_record.nspname = 'public' "
            "WHERE database_record.datname = current_database()"
        )
    ).one_or_none()
    expected = (contract.schema_owner_role, contract.schema_owner_role)
    if owners is None or tuple(str(value) for value in owners) != expected:
        raise ManagedPostgresRoleAuthorityError(
            "managed migration database/schema ownership is not exact"
        )


def assume_managed_postgres_schema_owner(
    connection: Connection,
    *,
    contract: ManagedPostgresRoleContract,
) -> None:
    """Prove the bounded migrator policy, then assume the NOLOGIN owner."""

    _assert_migrator_principal(connection, contract)
    _assert_role_attributes(connection, contract)
    _assert_role_membership(connection, contract)
    _assume_schema_owner(connection, contract)
    _assert_database_and_schema_owners(connection, contract)


__all__ = [
    "ManagedPostgresRoleAuthorityError",
    "assume_managed_postgres_schema_owner",
]
