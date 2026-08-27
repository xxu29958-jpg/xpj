from __future__ import annotations

from app.database._managed_postgres_contract import RUNTIME_READ_ONLY_TABLES
from app.database._runtime_authority_privileges import seal_runtime_authority_tables


class _Connection:
    def __init__(self, *, ready: bool) -> None:
        self.ready = ready
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))

    def scalar(self, statement: object) -> bool:
        self.statements.append(str(statement))
        return self.ready


def test_fresh_schema_seals_both_runtime_authority_tables() -> None:
    connection = _Connection(ready=True)

    assert seal_runtime_authority_tables(connection) is True  # type: ignore[arg-type]

    revoke, verify = connection.statements
    assert RUNTIME_READ_ONLY_TABLES == ("alembic_version", "dataset_authority")
    assert "REVOKE INSERT, UPDATE, DELETE" in revoke
    assert 'public."alembic_version"' in revoke
    assert 'public."dataset_authority"' in revoke
    assert "count(*) = 2" in verify
    assert "has_table_privilege('ticketbox_runtime'" in verify


def test_fresh_schema_rejects_an_incomplete_runtime_authority_postcondition() -> None:
    connection = _Connection(ready=False)

    assert seal_runtime_authority_tables(connection) is False  # type: ignore[arg-type]
