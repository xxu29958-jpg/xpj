from __future__ import annotations

from pathlib import Path

import pytest

from app.database._fresh_schema_upgrade import FreshSchemaUpgradeError, run_fresh_schema_upgrade_action


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
            database_url="postgresql+psycopg://ticketbox@127.0.0.1:5432/ticketbox?require_auth=scram-sha-256",
            pgpassfile=pgpass.resolve(),
            target_revision="20260821_0001",
            dataset_id="AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
            client_generation="11111111-1111-4111-8111-111111111111",
            schema_min_compatible="1.2.0",
            semantic_revision="ticketbox-dataset-semantics-v1",
            operation_id="op-1",
        )
