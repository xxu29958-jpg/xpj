"""Real PostgreSQL recovery/forward drill for the C07 deployment ceremony."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.database import _c07_ceremony as c07
from app.database import engine
from app.database._c07_ceremony import (
    C07_LIFECYCLE_PENDING,
    C07_LIFECYCLE_STATE_KEY,
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    C07ReceiptRepairRequiredError,
    assert_c07_lifecycle_ready,
    read_host_freeze_evidence,
    repair_c07_receipt_publication,
    run_c07_bigint_ceremony,
)
from app.database._core import _postgres_connect_args
from app.money_contract import MONEY_COLUMNS_V1
from app.services import backup_service
from app.services.secure_file import (
    hold_protected_file_for_read,
    write_protected_file_exclusive,
)
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import dedicated_test_database_lease
from tests._infra import c07_ceremony_postgres as c07_postgres

pytestmark = pytest.mark.real_db

_CEREMONY_ID = c07_postgres.CEREMONY_ID
_RELEASE_IDENTITY = c07_postgres.RELEASE_IDENTITY

@pytest.fixture
def _production_shaped_pgpass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Path]:
    """Project the test-cluster credential through the production ACL writer."""

    inherited = os.environ.get("PGPASSFILE")
    if not inherited:
        pytest.fail("the PostgreSQL test lane did not provide PGPASSFILE")
    source = Path(inherited)
    if not source.is_absolute():
        pytest.fail("the PostgreSQL test lane provided a relative PGPASSFILE")
    payload = source.read_text(encoding="utf-8")
    if not payload:
        pytest.fail("the PostgreSQL test lane provided an empty PGPASSFILE")

    projected = tmp_path / ".ticketbox-c07-test.pgpass"
    write_protected_file_exclusive(projected, payload)
    with hold_protected_file_for_read(projected) as protected:
        monkeypatch.setenv("PGPASSFILE", str(protected))
        yield protected


def _reset_source_to_c07_base() -> None:
    c07_postgres.reset_source_to_c07_base()


def _restore_url(source_url: str) -> str:
    return c07_postgres.restore_url(source_url)


def _write_isolated_freeze_proof(path: Path) -> None:
    c07_postgres.write_isolated_freeze_proof(path)


def _isolated_host(tmp_path: Path):
    return c07_postgres.isolated_host(tmp_path)


def _new_restore_engine(source_url: str):
    return c07_postgres.new_restore_engine(source_url)


def _assert_live_target_and_ready(receipt_dir: Path) -> None:
    c07_postgres.assert_live_target_and_ready(receipt_dir)


def test_c07_ceremony_restores_rolls_back_forwards_and_publishes_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    source_url = get_settings().database_url
    backup_dir = tmp_path / "backups"
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", backup_dir)
    lock_observations: list[str] = []
    original_drill = c07._isolated_restore_and_forward_drill  # noqa: SLF001
    original_stage = c07._write_receipt_pending  # noqa: SLF001

    def observe_drill(*args, **kwargs):
        assert backup_service._lock_path().is_file()  # noqa: SLF001
        lock_observations.append("isolated_restore")
        return original_drill(*args, **kwargs)

    def observe_stage(*args, **kwargs):
        assert backup_service._lock_path().is_file()  # noqa: SLF001
        lock_observations.append("receipt_staging")
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(c07, "_isolated_restore_and_forward_drill", observe_drill)
    monkeypatch.setattr(c07, "_write_receipt_pending", observe_stage)
    _reset_source_to_c07_base()
    host = _isolated_host(tmp_path)
    restore_url, restore_engine = _new_restore_engine(source_url)

    try:
        with dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
            passfile=os.environ.get("PGPASSFILE"),
        ):
            receipt_path = run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
    finally:
        restore_engine.dispose()

    assert lock_observations == ["isolated_restore", "receipt_staging"]
    assert backup_service._lock_path().exists()  # noqa: SLF001
    successor = backup_service.acquire_backup_job_lock()
    successor.release()
    assert receipt_path.parent == receipt_dir
    c07_postgres.assert_success_receipt(receipt_path, tmp_path=tmp_path)
    _assert_live_target_and_ready(receipt_dir)


def test_c07_snapshot_is_created_after_writer_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    """A commit immediately before the barrier must be present in the dump.

    This is the regression for the former REPEATABLE READ ordering, where
    identity reads fixed the source snapshot before SHARE locks were acquired
    and a writer could commit an invisible fact while the ceremony still
    reported a verified restore.
    """

    source_url = get_settings().database_url
    backup_dir = tmp_path / "backups"
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", backup_dir)
    original_barrier = c07._acquire_writer_barrier  # noqa: SLF001
    outsider = create_engine(
        source_url,
        connect_args=_postgres_connect_args(source_url),
        pool_pre_ping=True,
        future=True,
    )

    def commit_then_fence(connection, *, deadline):
        with outsider.begin() as writer:
            writer.execute(
                text(
                    "INSERT INTO app_meta (key, value, updated_at) "
                    "VALUES ('c07_snapshot_probe', 'committed-before-fence', "
                    "CURRENT_TIMESTAMP)"
                )
            )
        outsider.dispose()
        return original_barrier(connection, deadline=deadline)

    monkeypatch.setattr(c07, "_acquire_writer_barrier", commit_then_fence)
    _reset_source_to_c07_base()
    host = _isolated_host(tmp_path)
    restore_url, restore_engine = _new_restore_engine(source_url)

    try:
        with dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
            passfile=os.environ.get("PGPASSFILE"),
        ):
            run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
            with restore_engine.connect() as restored:
                assert (
                    restored.scalar(
                        text(
                            "SELECT value FROM app_meta "
                            "WHERE key = 'c07_snapshot_probe'"
                        )
                    )
                    == "committed-before-fence"
                )
    finally:
        outsider.dispose()
        restore_engine.dispose()


def test_c07_post_commit_receipt_publication_is_repairable_without_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    source_url = get_settings().database_url
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path / "backups")
    _reset_source_to_c07_base()
    host = _isolated_host(tmp_path)
    restore_url, restore_engine = _new_restore_engine(source_url)
    original_publish = c07._publish_receipt  # noqa: SLF001

    def fail_publication(*_args, **_kwargs):
        raise C07ReceiptRepairRequiredError("injected publication failure")

    monkeypatch.setattr(c07, "_publish_receipt", fail_publication)
    try:
        with dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
            passfile=os.environ.get("PGPASSFILE"),
        ), pytest.raises(
            C07ReceiptRepairRequiredError,
            match="injected publication failure",
        ):
            run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
    finally:
        restore_engine.dispose()

    temporary = receipt_dir / f".ticketbox-c07-{_CEREMONY_ID}.pending"
    final = receipt_dir / f"ticketbox-c07-{_CEREMONY_ID}.json"
    assert temporary.is_file()
    assert not final.exists()
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == C07_TARGET_REVISION
        )
        assert (
            connection.scalar(
                text("SELECT value FROM app_meta WHERE key = :key"),
                {"key": C07_LIFECYCLE_STATE_KEY},
            )
            == C07_LIFECYCLE_PENDING
        )
    with pytest.raises(C07ReceiptRepairRequiredError, match="not receipt-ready"):
        assert_c07_lifecycle_ready(engine, receipt_dir=receipt_dir)

    monkeypatch.setattr(c07, "_publish_receipt", original_publish)
    monkeypatch.setattr(
        c07,
        "_run_alembic_upgrade",
        lambda *_args, **_kwargs: pytest.fail("receipt repair must not rerun DDL"),
    )
    assert repair_c07_receipt_publication(
        engine,
        receipt_dir=receipt_dir,
    ) == final
    assert_c07_lifecycle_ready(engine, receipt_dir=receipt_dir)


def test_c07_commit_response_loss_preserves_receipt_for_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    """Server COMMIT + lost response must never erase the repair payload."""

    source_url = get_settings().database_url
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path / "backups")
    _reset_source_to_c07_base()
    host = _isolated_host(tmp_path)
    restore_url, restore_engine = _new_restore_engine(source_url)
    original_commit = engine.dialect.do_commit
    injected = False

    def commit_then_lose_response(dbapi_connection) -> None:
        nonlocal injected
        original_commit(dbapi_connection)
        if not injected:
            injected = True
            raise OSError("injected commit response loss")

    monkeypatch.setattr(
        engine.dialect,
        "do_commit",
        commit_then_lose_response,
    )
    try:
        with dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
            passfile=os.environ.get("PGPASSFILE"),
        ), pytest.raises(
            C07ReceiptRepairRequiredError,
            match="response was lost",
        ):
            run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
    finally:
        monkeypatch.setattr(engine.dialect, "do_commit", original_commit)
        restore_engine.dispose()

    temporary = receipt_dir / f".ticketbox-c07-{_CEREMONY_ID}.pending"
    final = receipt_dir / f"ticketbox-c07-{_CEREMONY_ID}.json"
    assert injected is True
    assert temporary.is_file()
    assert not final.exists()
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == C07_TARGET_REVISION
        )
        assert (
            connection.scalar(
                text("SELECT value FROM app_meta WHERE key = :key"),
                {"key": C07_LIFECYCLE_STATE_KEY},
            )
            == C07_LIFECYCLE_PENDING
        )

    assert repair_c07_receipt_publication(
        engine,
        receipt_dir=receipt_dir,
    ) == final
    assert_c07_lifecycle_ready(engine, receipt_dir=receipt_dir)


def test_c07_rollback_before_commit_removes_only_matching_pending_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    """A fresh source/int4 recheck is the only safe automatic cleanup."""

    class InjectedRollbackBeforeCommitError(RuntimeError):
        pass

    source_url = get_settings().database_url
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path / "backups")
    _reset_source_to_c07_base()
    host = _isolated_host(tmp_path)
    restore_url, restore_engine = _new_restore_engine(source_url)
    original_commit = engine.dialect.do_commit

    def rollback_then_fail(dbapi_connection) -> None:
        dbapi_connection.rollback()
        raise InjectedRollbackBeforeCommitError(
            "injected rollback before commit"
        )

    monkeypatch.setattr(engine.dialect, "do_commit", rollback_then_fail)
    try:
        with dedicated_test_database_lease(
            restore_url,
            expected_database=TEST_POSTGRES_CONTRACT.restore_database,
            reset=True,
            cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
            passfile=os.environ.get("PGPASSFILE"),
        ), pytest.raises(
            InjectedRollbackBeforeCommitError,
            match="injected rollback before commit",
        ):
            run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
    finally:
        monkeypatch.setattr(engine.dialect, "do_commit", original_commit)
        restore_engine.dispose()

    assert not (
        receipt_dir / f".ticketbox-c07-{_CEREMONY_ID}.pending"
    ).exists()
    assert not (
        receipt_dir / f"ticketbox-c07-{_CEREMONY_ID}.json"
    ).exists()
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == C07_SOURCE_REVISION
        )
        for contract in MONEY_COLUMNS_V1:
            assert (
                str(
                    {
                        item["name"]: item
                        for item in inspect(connection).get_columns(
                            contract.table
                        )
                    }[contract.column]["type"]
                ).lower()
                == "integer"
            )


def test_c07_host_identity_change_after_stage_rolls_back_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _production_shaped_pgpass: Path,
) -> None:
    c07_postgres.exercise_host_identity_change_retry(tmp_path, monkeypatch)


def test_c07_unknown_source_session_refuses_before_backup_or_ddl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = get_settings().database_url
    restore_url = _restore_url(source_url)
    proof_path = tmp_path / "writer-freeze.json"
    backup_dir = tmp_path / "backups"
    receipt_dir = tmp_path / "receipts"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", backup_dir)
    _reset_source_to_c07_base()
    _write_isolated_freeze_proof(proof_path)
    host = read_host_freeze_evidence(
        proof_path,
        expected_release_identity=_RELEASE_IDENTITY,
        expected_parent_pid=os.getpid(),
        allow_isolated_test=True,
    )
    restore_engine = create_engine(
        restore_url,
        connect_args=_postgres_connect_args(restore_url),
        pool_pre_ping=True,
        future=True,
    )
    blocker = engine.connect()
    try:
        with pytest.raises(c07.C07CeremonyError, match="another client session"):
            run_c07_bigint_ceremony(
                source_engine=engine,
                source_url=source_url,
                restore_engine=restore_engine,
                restore_url=restore_url,
                host_evidence=host,
                postgres_data_directory=tmp_path,
                receipt_dir=receipt_dir,
            )
    finally:
        blocker.close()
        restore_engine.dispose()

    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == C07_SOURCE_REVISION
        )
    assert not list(receipt_dir.glob("*"))
    assert not list(backup_dir.glob("*.dump"))
