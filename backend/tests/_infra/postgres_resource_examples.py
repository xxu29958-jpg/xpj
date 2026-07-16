"""Resource-classifier examples that live outside the collecting test module."""

from __future__ import annotations

_DROP_ROLE_SQL = "DROP ROLE IF EXISTS xpj_resource_contract_role"


def imported_cluster_helper(connection: object) -> None:
    connection.execute(_DROP_ROLE_SQL)  # type: ignore[attr-defined]


class ImportedClusterHelper:
    @staticmethod
    def drop_role(connection: object) -> None:
        connection.execute(_DROP_ROLE_SQL)  # type: ignore[attr-defined]


def imported_cluster_fixture() -> ImportedClusterHelper:
    return ImportedClusterHelper()
