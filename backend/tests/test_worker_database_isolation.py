from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from tests._infra import db as db_infra
from tests._infra.worker_db import (
    drop_worker_database,
    recreate_worker_database,
    worker_database_url,
)


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
    with pytest.raises(ValueError, match="xpj_test_<run>_gwN"):
        operation("postgresql+psycopg://postgres@localhost:5432/ticketbox")


def test_schema_reset_refuses_non_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ProductionEngineStub:
        url = make_url("postgresql+psycopg://postgres@localhost:5432/ticketbox")

    monkeypatch.setattr(db_infra, "engine", ProductionEngineStub())

    with pytest.raises(RuntimeError, match="non-test PostgreSQL"):
        db_infra.reset_db_state()
