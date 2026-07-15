from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from tests._infra import db as db_infra
from tests._infra.worker_db import (
    configured_test_database_url,
    drop_worker_database,
    recreate_worker_database,
    worker_database_url,
)


def test_database_url_override_requires_explicit_cluster_confirmation() -> None:
    override = "postgresql+psycopg://postgres@localhost:5432/xpj_test"

    with pytest.raises(RuntimeError, match="XPJ_TEST_CLUSTER_CONFIRMED=1"):
        configured_test_database_url({"XPJ_TEST_DATABASE_URL": override})

    assert configured_test_database_url({}) == (
        "postgresql+psycopg://postgres@localhost:5438/xpj_test"
    )
    assert configured_test_database_url(
        {
            "XPJ_TEST_DATABASE_URL": override,
            "XPJ_TEST_CLUSTER_CONFIRMED": "1",
        }
    ) == override


def test_worker_database_url_preserves_connection_contract() -> None:
    result = worker_database_url(
        "postgresql+psycopg://tester:secret@localhost:5438/xpj_test?sslmode=disable",
        "gw3",
        "run-alpha",
    )
    other_run = worker_database_url(
        "postgresql+psycopg://tester:secret@localhost:5438/xpj_test?sslmode=disable",
        "gw3",
        "run-beta",
    )

    parsed = make_url(result)
    assert parsed.database is not None
    assert parsed.database.startswith("xpj_test_")
    assert parsed.database.endswith("_gw3")
    assert parsed.database != make_url(other_run).database
    assert parsed.username == "tester"
    assert parsed.password == "secret"
    assert parsed.port == 5438
    assert parsed.query["sslmode"] == "disable"


@pytest.mark.parametrize("worker_id", ["master", "gw", "gw-1", "gw1_extra"])
def test_worker_database_url_rejects_invalid_worker_id(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker id"):
        worker_database_url(
            "postgresql+psycopg://postgres@localhost:5438/xpj_test",
            worker_id,
            "run-alpha",
        )


def test_worker_database_url_refuses_non_test_database() -> None:
    with pytest.raises(ValueError, match="xpj_test base"):
        worker_database_url(
            "postgresql+psycopg://postgres@localhost:5432/ticketbox",
            "gw0",
            "run-alpha",
        )


def test_worker_database_url_refuses_non_postgresql_engine() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        worker_database_url("sqlite:///xpj_test", "gw0", "run-alpha")


@pytest.mark.parametrize(
    "operation",
    [recreate_worker_database, drop_worker_database],
)
def test_worker_lifecycle_refuses_non_worker_database(operation) -> None:
    current_run = "run-alpha"
    worker_id = "gw0"
    with pytest.raises(ValueError, match="current xpj_test_<run>_gwN"):
        operation(
            "postgresql+psycopg://postgres@localhost:5432/ticketbox",
            worker_id=worker_id,
            run_uid=current_run,
        )

    another_run_url = worker_database_url(
        "postgresql+psycopg://postgres@localhost:5438/xpj_test",
        worker_id,
        "run-beta",
    )
    with pytest.raises(ValueError, match="current xpj_test_<run>_gwN"):
        operation(
            another_run_url,
            worker_id=worker_id,
            run_uid=current_run,
        )


def test_schema_reset_refuses_non_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProductionEngineStub:
        url = make_url("postgresql+psycopg://postgres@localhost:5432/ticketbox")

    monkeypatch.setattr(db_infra, "engine", ProductionEngineStub())

    with pytest.raises(RuntimeError, match="non-test PostgreSQL"):
        db_infra.reset_db_state()
