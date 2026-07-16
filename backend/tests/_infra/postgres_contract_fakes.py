"""Reusable PostgreSQL authority and lock fakes for contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import test_pg_contract
from scripts.test_pg_protected_file import write_protected_utf8_file


def owned_environment(
    tmp_path: Path,
    *,
    port: int = 5544,
) -> tuple[str, dict[str, str]]:
    data_directory = tmp_path / f"cluster-{port}"
    data_directory.mkdir()
    marker_path = data_directory / ".xpj-test-cluster.json"
    write_protected_utf8_file(
        marker_path,
        json.dumps(
            {
                "schema_version": 3,
                "kind": "xiaopiaojia-test-postgres",
                "purpose": "local",
                "port": port,
                "instance_id": "a" * 32,
                "system_identifier": "1234567890123456789",
                "authentication": "scram-sha-256",
            }
        ),
        label="Fake owned PostgreSQL marker",
    )
    credential_path = data_directory / ".xpj-test-postgres-password"
    write_protected_utf8_file(
        credential_path,
        "c" * 43 + "\n",
        label="Fake owned PostgreSQL credential",
    )
    database_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/xpj_test"
    return database_url, {
        "XPJ_TEST_DATABASE_URL": database_url,
        test_pg_contract.TEST_CLUSTER_AUTHORITY_ENV:
            test_pg_contract.OWNED_MARKER_AUTHORITY,
        test_pg_contract.TEST_CLUSTER_INSTANCE_ID_ENV: "a" * 32,
        test_pg_contract.TEST_CLUSTER_MARKER_PATH_ENV: str(marker_path),
        test_pg_contract.TEST_CLUSTER_SYSTEM_IDENTIFIER_ENV:
            "1234567890123456789",
        test_pg_contract.TEST_POSTGRES_CREDENTIAL_FILE_ENV: str(credential_path),
    }


def fake_lock_events(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        test_pg_contract,
        "assert_test_cluster_authority",
        lambda *_args, **_kwargs: None,
    )

    class FakeResult:
        def fetchone(self) -> tuple[bool]:
            return (True,)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            events.append(("closed", None))

        def execute(self, statement: str, parameters: tuple[str | int, ...]):
            events.append((statement, parameters))
            return FakeResult()

    def fake_connect(**arguments):
        events.append(("connect", arguments))
        return FakeConnection()

    monkeypatch.setattr(test_pg_contract.psycopg, "connect", fake_connect)
    return events
