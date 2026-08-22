from __future__ import annotations

from pathlib import Path

import pytest

PACKAGING = Path(__file__).resolve().parents[1]


def test_restore_drill_cleanup_attempts_each_independent_repair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PACKAGING.parent))
    from scripts import postgres_restore_drill_topology

    calls: list[str] = []
    first_failure = KeyboardInterrupt("cleanup-1")
    third_failure = SystemExit("cleanup-3")

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            calls.append(statement.as_string())
            if len(calls) == 1:
                raise first_failure
            if len(calls) == 3:
                raise third_failure

    monkeypatch.setattr(
        postgres_restore_drill_topology.psycopg,
        "connect",
        lambda *_args, **_kwargs: Connection(),
    )
    contract = postgres_restore_drill_topology._TopologyContract(  # noqa: SLF001
        admin_conninfo="admin",
        admin_restore_conninfo="restore",
        database="xpj_restore_test",
        migrator="xpj_test_app",
        owner="xpj_drill_owner_test",
        passfile=tmp_path / "test.pgpass",
    )
    failures = postgres_restore_drill_topology._cleanup_topology(  # noqa: SLF001
        contract,
        postgres_restore_drill_topology._TopologyState(  # noqa: SLF001
            role_created=True,
            migrator_changed=True,
        ),
    )

    assert calls == [
        'REASSIGN OWNED BY "xpj_drill_owner_test" TO "xpj_test_app"',
        'ALTER SCHEMA public OWNER TO "xpj_test_app"',
        'ALTER DATABASE "xpj_restore_test" OWNER TO "xpj_test_app"',
        'REVOKE "xpj_drill_owner_test" FROM "xpj_test_app"',
        'DROP ROLE "xpj_drill_owner_test"',
        'ALTER ROLE "xpj_test_app" INHERIT',
    ]
    assert len(failures) == 2
    assert failures[0] is first_failure
    assert failures[1] is third_failure


def test_restore_drill_preserves_body_and_connection_cleanup_baseexceptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PACKAGING.parent))
    from scripts import postgres_restore_drill_topology

    contract = postgres_restore_drill_topology._TopologyContract(  # noqa: SLF001
        admin_conninfo="admin",
        admin_restore_conninfo="restore",
        database="xpj_restore_test",
        migrator="xpj_test_app",
        owner="xpj_drill_owner_test",
        passfile=tmp_path / "test.pgpass",
    )
    body_failure = ValueError("body")
    final_cleanup_failure = SystemExit("final-cleanup")

    class FinalCleanupConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _statement: object) -> None:
            raise final_cleanup_failure

    monkeypatch.setattr(
        postgres_restore_drill_topology,
        "_resolve_topology_contract",
        lambda **_kwargs: contract,
    )

    def installed(_contract: object, state: object) -> None:
        state.migrator_changed = True

    monkeypatch.setattr(postgres_restore_drill_topology, "_install_topology", installed)
    monkeypatch.setattr(
        postgres_restore_drill_topology.psycopg,
        "connect",
        lambda *_args, **_kwargs: FinalCleanupConnection(),
    )
    with (
        pytest.raises(BaseExceptionGroup) as grouped,
        postgres_restore_drill_topology.managed_restore_role_topology(
            restore_url="postgresql://unused",
            passfile=contract.passfile,
        ),
    ):
        raise body_failure
    assert grouped.value.exceptions[0] is body_failure
    assert grouped.value.exceptions[1] is final_cleanup_failure

    connection_failure = KeyboardInterrupt("restore-connect")
    attempted: list[str] = []

    class EnterFailure:
        def __enter__(self):
            raise connection_failure

        def __exit__(self, *_args: object) -> None:
            return None

    class RepairConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            attempted.append(statement.as_string())

    connections = iter((EnterFailure(), RepairConnection(), RepairConnection()))
    monkeypatch.setattr(
        postgres_restore_drill_topology.psycopg,
        "connect",
        lambda *_args, **_kwargs: next(connections),
    )
    failures = postgres_restore_drill_topology._cleanup_topology(  # noqa: SLF001
        contract,
        postgres_restore_drill_topology._TopologyState(  # noqa: SLF001
            role_created=True,
            migrator_changed=True,
        ),
    )
    assert failures == [connection_failure]
    assert attempted == [
        'ALTER DATABASE "xpj_restore_test" OWNER TO "xpj_test_app"',
        'REVOKE "xpj_drill_owner_test" FROM "xpj_test_app"',
        'DROP ROLE "xpj_drill_owner_test"',
        'ALTER ROLE "xpj_test_app" INHERIT',
    ]
