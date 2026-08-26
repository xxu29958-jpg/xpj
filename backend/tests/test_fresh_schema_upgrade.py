from __future__ import annotations

from pathlib import Path

import pytest

from app.database import _fresh_schema_upgrade as fresh_schema
from app.database._fresh_schema_upgrade import FreshSchemaUpgradeError, run_fresh_schema_upgrade_action


class _HolderSentinelError(Exception):
    pass


def test_fresh_schema_upgrade_enters_the_installer_machine_secret_holder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pgpass = (tmp_path / "pgpass").resolve()

    def stop_at_holder(path: Path) -> None:
        assert path == pgpass
        raise _HolderSentinelError

    monkeypatch.setattr(fresh_schema, "hold_installer_machine_secret_for_read", stop_at_holder)
    with pytest.raises(_HolderSentinelError):
        fresh_schema._execute_fresh_upgrade(
            parsed_url=object(),
            pgpassfile=pgpass,
            target="20260821_0001",
            dataset_id="11111111-1111-4111-8111-111111111111",
            client_generation="11111111-1111-4111-8111-111111111111",
            schema_min_compatible="20260722_0001",
            semantic_revision="ticketbox-dataset-semantics-v1",
        )


def test_fresh_schema_upgrade_rejects_password_in_url(tmp_path: Path) -> None:
    pgpass = tmp_path / "pgpass"
    pgpass.write_text("127.0.0.1:5432:ticketbox:ticketbox:secret\n", encoding="utf-8")
    with pytest.raises(FreshSchemaUpgradeError):
        run_fresh_schema_upgrade_action(
            database_url=(
                "postgresql+psycopg://ticketbox:secret@127.0.0.1:5432/ticketbox"
                "?require_auth=scram-sha-256"
            ),
            pgpassfile=pgpass.resolve(),
            target_revision="20260821_0001",
            dataset_id="11111111-1111-4111-8111-111111111111",
            client_generation="11111111-1111-4111-8111-111111111111",
            schema_min_compatible="1.2.0",
            semantic_revision="ticketbox-dataset-semantics-v1",
            operation_id="op-1",
        )


def test_fresh_schema_upgrade_rejects_non_canonical_dataset_id(tmp_path: Path) -> None:
    pgpass = tmp_path / "pgpass"
    pgpass.write_text("x\n", encoding="utf-8")
    with pytest.raises(FreshSchemaUpgradeError, match="dataset_id"):
        run_fresh_schema_upgrade_action(
            database_url="postgresql+psycopg://ticketbox_migrator@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256",
            pgpassfile=pgpass.resolve(),
            target_revision="20260821_0001",
            dataset_id="AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
            client_generation="11111111-1111-4111-8111-111111111111",
            schema_min_compatible="1.2.0",
            semantic_revision="ticketbox-dataset-semantics-v1",
            operation_id="op-1",
        )


def test_fresh_schema_real_caller_seals_runtime_authority_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ActiveConnection:
        def in_transaction(self) -> bool:
            return True

    target = "20260821_0001"
    connection = _ActiveConnection()
    sealed: list[object] = []

    def seal_runtime_authority_tables(actual: object) -> bool:
        sealed.append(actual)
        return True

    monkeypatch.setattr(fresh_schema, "assume_managed_postgres_schema_owner", lambda *_a, **_k: None)
    monkeypatch.setattr(fresh_schema, "_current_revision", lambda _connection: target)
    monkeypatch.setattr(fresh_schema, "_bind_dataset_authority", lambda *_a, **_k: None)
    monkeypatch.setattr(
        fresh_schema,
        "seal_runtime_authority_tables",
        seal_runtime_authority_tables,
    )

    result = fresh_schema._run_on_connection(
        connection,  # type: ignore[arg-type]
        target_revision=target,
        dataset_id="11111111-1111-4111-8111-111111111111",
        client_generation="11111111-1111-4111-8111-111111111111",
        schema_min_compatible="1.2.0",
        semantic_revision="ticketbox-dataset-semantics-v1",
    )

    assert result == "already-at-target"
    assert sealed == [connection]
