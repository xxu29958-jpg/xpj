from __future__ import annotations

from types import SimpleNamespace

import conftest as suite_conftest
import pytest
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.database._lifecycle import load_alembic_context
from app.models import DatasetAuthorityRecord
from scripts.run_postgres_pytest_lane import (
    POSTGRES_PYTEST_LANE_DEST,
    POSTGRES_PYTEST_SHARD_COUNT_DEST,
)
from tests._infra import db as test_db


class _LifecycleConfig:
    def __init__(self, *, lane: str | None, shard_count: int) -> None:
        self._options = {
            POSTGRES_PYTEST_LANE_DEST: lane,
            POSTGRES_PYTEST_SHARD_COUNT_DEST: shard_count,
        }

    def getoption(self, name: str) -> object:
        return self._options[name]


def _fixture_request(*, lane: str | None, shard_count: int) -> SimpleNamespace:
    return SimpleNamespace(
        config=_LifecycleConfig(lane=lane, shard_count=shard_count),
        keywords={"real_db": True},
    )


def _run_real_db_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lane: str | None,
    shard_count: int,
    fail_test: bool = False,
) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(suite_conftest, "reset_db_state", lambda: calls.append("reset"))
    monkeypatch.setattr(suite_conftest, "clear_db_state", lambda: calls.append("clear"))
    fixture = suite_conftest._db_isolation.__wrapped__(  # noqa: SLF001
        _fixture_request(lane=lane, shard_count=shard_count)
    )
    next(fixture)
    if fail_test:
        with pytest.raises(RuntimeError, match="simulated test failure"):
            fixture.throw(RuntimeError("simulated test failure"))
    else:
        with pytest.raises(StopIteration):
            next(fixture)
    return calls


@pytest.mark.parametrize("fail_test", [False, True])
def test_sharded_real_db_lifecycle_rebuilds_before_and_clears_after(
    monkeypatch: pytest.MonkeyPatch,
    fail_test: bool,
) -> None:
    assert _run_real_db_fixture(
        monkeypatch,
        lane="real-db",
        shard_count=4,
        fail_test=fail_test,
    ) == ["reset", "clear"]


@pytest.mark.parametrize(
    ("lane", "shard_count"),
    [(None, 1), (None, 4), ("ordinary", 4), ("real-db", 1)],
)
def test_other_real_db_invocations_keep_the_rebuilt_teardown_baseline(
    monkeypatch: pytest.MonkeyPatch,
    lane: str | None,
    shard_count: int,
) -> None:
    assert _run_real_db_fixture(
        monkeypatch,
        lane=lane,
        shard_count=shard_count,
    ) == ["reset", "reset"]


def test_optimized_lane_still_rejects_a_mixed_collection() -> None:
    config = _LifecycleConfig(lane="real-db", shard_count=4)
    session = SimpleNamespace(
        config=config,
        items=[
            SimpleNamespace(keywords={"real_db": True}),
            SimpleNamespace(keywords={}),
        ],
    )

    with pytest.raises(pytest.UsageError, match="real-db PostgreSQL lane"):
        suite_conftest.pytest_collection_finish(session)


@pytest.mark.real_db
@pytest.mark.currency_binding_unbound
def test_clear_then_full_reset_restores_schema_migration_seed_and_files() -> None:
    runtime_path = test_db._DATA_RUNTIME_ROOT / test_db.TEST_RUN_ID  # noqa: SLF001
    runtime_path.mkdir(parents=True, exist_ok=True)
    (runtime_path / "sentinel.txt").write_text("owned test data", encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE lifecycle_teardown_sentinel (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO lifecycle_teardown_sentinel (id) VALUES (1)"))
        connection.execute(text("DROP TABLE alembic_version"))

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.alembic_version')")) is None

    test_db.clear_db_state()

    assert not runtime_path.exists()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.lifecycle_teardown_sentinel')")) is None
        assert connection.scalar(
            text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
        ) == 0

    test_db.reset_db_state()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            load_alembic_context().head_revision
        )
        assert connection.scalar(text("SELECT to_regclass('public.lifecycle_teardown_sentinel')")) is None
    with SessionLocal() as db:
        assert db.get(DatasetAuthorityRecord, 1) is not None
