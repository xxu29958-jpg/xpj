"""Failure-preservation tests for the throwaway PostgreSQL topology oracle."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._infra.postgres_topology_cleanup import cleanup_postgres_topology


class _Cursor:
    def __init__(self, *, row=None, rows=()) -> None:
        self._row = row
        self._rows = rows

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FailingAdmin:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def execute(self, _statement, _parameters=None):
        call = self.calls
        self.calls += 1
        if call == 0:
            raise KeyboardInterrupt("terminate failed")
        if call == 1:
            raise SystemExit("drop database failed")
        if call == 3:
            return _Cursor(row=(True,))
        if call == 4:
            return _Cursor(rows=(("leftover_role",),))
        return _Cursor()

    def close(self) -> None:
        self.closed = True
        raise RuntimeError("close failed")


def test_cleanup_attempts_every_step_and_preserves_all_failures() -> None:
    admin = _FailingAdmin()
    with pytest.raises(BaseExceptionGroup) as captured:
        cleanup_postgres_topology(
            admin=admin,
            database="throwaway_database",
            roles=("throwaway_owner", "throwaway_migrator"),
        )

    assert admin.calls == 5
    assert admin.closed is True
    assert tuple(type(exc) for exc in captured.value.exceptions) == (
        KeyboardInterrupt,
        SystemExit,
        AssertionError,
        RuntimeError,
    )


def test_managed_topology_preserves_body_and_cleanup_failures(monkeypatch) -> None:
    from tests import test_managed_postgres_migration_runtime as runtime_test

    body_error = ValueError("body failed")
    cleanup_error = KeyboardInterrupt("cleanup failed")
    topology = SimpleNamespace(
        admin=object(),
        database="throwaway_database",
        runtime_role="throwaway_runtime",
        migrator="throwaway_migrator",
        owner="throwaway_owner",
    )
    monkeypatch.setattr(runtime_test, "_new_managed_topology", lambda _path: topology)
    monkeypatch.setattr(
        runtime_test,
        "_create_roles_and_database",
        lambda _topology: (_ for _ in ()).throw(body_error),
    )
    monkeypatch.setattr(
        runtime_test,
        "cleanup_postgres_topology",
        lambda **_kwargs: (_ for _ in ()).throw(cleanup_error),
    )

    with (
        pytest.raises(BaseExceptionGroup) as captured,
        runtime_test._managed_topology(SimpleNamespace(), monkeypatch),
    ):
        raise AssertionError("unreachable")
    assert captured.value.exceptions == (body_error, cleanup_error)
