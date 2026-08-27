from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database._database_generation_runtime_admission import (
    assert_database_generation_startup_ready,
)
from app.database._database_generation_runtime_queries import RUNTIME_AUTHORITY_QUERY
from app.database._lifecycle import DatabaseMigrationPreflightError

INSTALL_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "22222222-2222-4222-8222-222222222222"
TARGET_REVISION = "20260821_0001"


class _Rows:
    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)


class _Result:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _Connection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row
        self.executed_statement: object | None = None

    def scalars(self, _statement: object) -> _Rows:
        return _Rows((TARGET_REVISION,))

    def execute(self, statement: object) -> _Result:
        self.executed_statement = statement
        return _Result(self._row)


class _Engine:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.connection = _Connection(row)
        self.connect_count = 0

    def connect(self):
        self.connect_count += 1
        return nullcontext(self.connection)


def _row(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "session_user": "ticketbox_runtime",
        "current_user": "ticketbox_runtime",
        "current_database": "ticketbox",
        "runtime_role_ready": True,
        "runtime_role_isolated": True,
        "runtime_database_ready": True,
        "runtime_schema_ready": True,
        "runtime_tables_ready": True,
        "runtime_sequences_ready": True,
        "dataset_id": DATASET_ID,
        "client_generation": INSTALL_ID,
        "restore_epoch": 0,
        "schema_revision": TARGET_REVISION,
        "schema_min_compatible": "1.2.0",
        "semantic_revision": "ticketbox-dataset-semantics-v1",
        "restored_from_backup_id": None,
    }
    values.update(changes)
    return values


def _program() -> SimpleNamespace:
    return SimpleNamespace(target_revision=TARGET_REVISION)


def test_installed_runtime_requires_explicit_instance_and_dataset_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TICKETBOX_INSTALLATION_ID", raising=False)
    monkeypatch.delenv("TICKETBOX_DATASET_ID", raising=False)
    engine = _Engine(_row())

    with pytest.raises(DatabaseMigrationPreflightError, match="explicit runtime identity"):
        assert_database_generation_startup_ready(engine, _program())

    assert engine.connect_count == 0


def test_installed_runtime_admits_exact_live_dataset_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", INSTALL_ID)
    monkeypatch.setenv("TICKETBOX_DATASET_ID", DATASET_ID)
    engine = _Engine(_row())

    assert_database_generation_startup_ready(engine, _program())

    assert engine.connection.executed_statement is RUNTIME_AUTHORITY_QUERY


def test_runtime_authority_query_rejects_ownership_and_all_role_memberships() -> None:
    statement = str(RUNTIME_AUTHORITY_QUERY)

    assert "database_record.datdba <> runtime_role.oid" in statement
    assert "namespace_record.nspowner <> runtime_role.oid" in statement
    assert "pg_catalog.pg_auth_members AS membership" in statement
    assert "membership.member = runtime_role.oid" in statement
    assert "pg_has_role" not in statement
    assert "relation.relname IN ('alembic_version', 'dataset_authority')" in statement
    assert "NOT has_table_privilege(session_user, relation.oid, 'INSERT')" in statement
    assert "NOT has_table_privilege(session_user, relation.oid, 'UPDATE')" in statement
    assert "NOT has_table_privilege(session_user, relation.oid, 'DELETE')" in statement


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"session_user": "postgres"}, "runtime role"),
        ({"current_user": "ticketbox_owner"}, "runtime role"),
        ({"current_database": "postgres"}, "runtime database"),
        ({"runtime_role_ready": False}, "runtime role policy"),
        ({"runtime_role_isolated": False}, "runtime role isolation"),
        ({"runtime_database_ready": False}, "runtime database privileges"),
        ({"runtime_schema_ready": False}, "runtime schema privileges"),
        ({"runtime_tables_ready": False}, "runtime table privileges"),
        ({"runtime_sequences_ready": False}, "runtime sequence privileges"),
        ({"dataset_id": "33333333-3333-4333-8333-333333333333"}, "dataset_id"),
        ({"client_generation": "33333333-3333-4333-8333-333333333333"}, "installation_id"),
        ({"restore_epoch": 1}, "fresh dataset"),
        ({"restored_from_backup_id": "backup-1"}, "fresh dataset"),
        ({"schema_revision": "20260809_0001"}, "installed program target"),
        ({"semantic_revision": "ticketbox-dataset-semantics-v2"}, "dataset semantics"),
    ],
)
def test_installed_runtime_rejects_non_exact_live_authority(
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setenv("TICKETBOX_INSTALLATION_ID", INSTALL_ID)
    monkeypatch.setenv("TICKETBOX_DATASET_ID", DATASET_ID)

    with pytest.raises(DatabaseMigrationPreflightError, match=message):
        assert_database_generation_startup_ready(_Engine(_row(**changes)), _program())


def test_runtime_admission_source_has_no_generation_current_fallback() -> None:
    import app.database._database_generation_runtime_admission as admission

    source = Path(admission.__file__).read_text(encoding="utf-8")
    assert "current-generation.json" not in source
    assert "_current_projection_present" not in source
