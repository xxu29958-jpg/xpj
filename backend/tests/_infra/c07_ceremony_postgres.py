"""Shared setup and scenario helpers for the real PostgreSQL C07 drill."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from app.config import get_settings
from app.database import SessionLocal, engine
from app.database import _c07_ceremony as c07
from app.database._c07_ceremony import (
    C07_SOURCE_REVISION,
    C07_TARGET_REVISION,
    _canonical_json,
    assert_c07_lifecycle_ready,
    read_host_freeze_evidence,
    run_c07_bigint_ceremony,
)
from app.database._core import _postgres_connect_args
from app.models import Expense
from app.money_contract import (
    MONEY_COLUMNS_V1,
    MONEY_FINAL_CHECKS_V1,
    MONEY_REMOVED_LEGACY_CHECKS_V1,
)
from app.services import backup_service
from app.services.identity_service import (
    ensure_identity_for_existing_ledger_ids,
)
from app.services.secure_file import write_protected_file_exclusive
from scripts.test_postgres_contract import TEST_POSTGRES_CONTRACT
from scripts.test_postgres_database import dedicated_test_database_lease

CEREMONY_ID = "66d65d05-c93a-4fde-b544-5578b6bfa18f"
RELEASE_IDENTITY = "c" * 40


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    return config


def reset_source_to_c07_base() -> None:
    engine.dispose()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    config = _alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, C07_SOURCE_REVISION)
    with SessionLocal() as session:
        ensure_identity_for_existing_ledger_ids(session, {"owner"})
        session.commit()
    with SessionLocal() as session:
        session.add(
            Expense(
                tenant_id="owner",
                amount_cents=12_345,
                home_currency_code="CNY",
                original_currency_code="CNY",
                original_amount_minor=12_345,
                exchange_rate_to_cny=Decimal("1"),
                exchange_rate_date=date(2026, 7, 20),
                exchange_rate_source="base",
                fx_status="ready",
                merchant="C07 recovery fixture",
            )
        )
        session.commit()
    engine.dispose()


def restore_url(source_url: str) -> str:
    return make_url(source_url).set(
        database=TEST_POSTGRES_CONTRACT.restore_database
    ).render_as_string(hide_password=False)


def write_isolated_freeze_proof(path: Path) -> None:
    now = datetime.now(UTC)
    proof = {
        "schema": "ticketbox-c07-isolated-freeze-v1",
        "operation_id": CEREMONY_ID,
        "release_identity": RELEASE_IDENTITY,
        "mode": "isolated_test",
        "authority_digest": "d" * 64,
        "lifecycle_lock_held": True,
        "backend_service_state": "stopped",
        "runtime_process_count": 0,
        "listener_pid_count": 0,
        "coordinator_pid": os.getpid(),
        "recorded_at_utc": now.isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (now + timedelta(minutes=15))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    write_protected_file_exclusive(path, _canonical_json(proof))


def isolated_host(tmp_path: Path):
    proof_path = tmp_path / "writer-freeze.json"
    write_isolated_freeze_proof(proof_path)
    return read_host_freeze_evidence(
        proof_path,
        expected_release_identity=RELEASE_IDENTITY,
        expected_parent_pid=os.getpid(),
        allow_isolated_test=True,
    )


def new_restore_engine(source_url: str) -> tuple[str, Engine]:
    target_url = restore_url(source_url)
    return target_url, create_engine(
        target_url,
        connect_args=_postgres_connect_args(target_url),
        pool_pre_ping=True,
        future=True,
    )


def assert_success_receipt(receipt_path: Path, *, tmp_path: Path) -> None:
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["result"] == "target_committed"
    assert receipt["source_revision"] == C07_SOURCE_REVISION
    assert receipt["target_revision"] == C07_TARGET_REVISION
    assert receipt["writer_freeze"]["mode"] == "isolated_test"
    assert receipt["capacity"]["result"] == "sufficient"
    assert receipt["backup"]["result"] == "verified"
    assert receipt["backup"]["size_bytes"] > 0
    assert receipt["backup"]["pg_restore_list_entry_count"] > 0
    assert receipt["isolated_recovery"]["failure_rollback_verified"] is True
    assert receipt["isolated_recovery"]["forward_repair_verified"] is True
    assert receipt["isolated_recovery"]["total_rows"] > 0
    assert receipt["target_shape"]["column_count"] == len(MONEY_COLUMNS_V1)
    assert receipt["target_shape"]["check_count"] == len(MONEY_FINAL_CHECKS_V1)
    assert receipt["target_shape"]["absent_check_count"] == len(
        MONEY_REMOVED_LEGACY_CHECKS_V1
    )
    assert {
        (item["table"], item["name"], item["absent"])
        for item in receipt["target_shape"]["absent_checks"]
    } == {
        (check.table, check.name, True)
        for check in MONEY_REMOVED_LEGACY_CHECKS_V1
    }
    assert receipt["statistics_refresh"]["result"] == "verified"
    assert receipt["statistics_refresh"]["table_count"] == 18
    assert receipt["statistics_refresh"]["elapsed_ms"] >= 0
    assert receipt["assets"] == {
        "result": "verified_empty_isolated_test_fixture",
        "production_authorized": False,
        "database_reference_count": 0,
        "logical_generation_digest": receipt["database_identity"]["logical_digest"],
    }
    assert b"postgresql://" not in receipt_bytes
    assert str(tmp_path).encode() not in receipt_bytes


def assert_live_target_and_ready(receipt_dir: Path) -> None:
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == C07_TARGET_REVISION
        )
        assert (
            connection.scalar(
                text("SELECT value FROM app_meta WHERE key = :key"),
                {"key": c07.C07_LIFECYCLE_STATE_KEY},
            )
            == c07.C07_LIFECYCLE_READY
        )
        inspector = inspect(connection)
        for contract in MONEY_COLUMNS_V1:
            column = {
                item["name"]: item
                for item in inspector.get_columns(contract.table)
            }[contract.column]
            assert "bigint" in str(column["type"]).lower()
    assert_c07_lifecycle_ready(engine, receipt_dir=receipt_dir)


def _run_identity_change_failure(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_url: str,
    restore_url_value: str,
    restore_engine: Engine,
    host,
    receipt_dir: Path,
    pending: Path,
    original_assert,
) -> bool:
    injected = False

    def reject_after_stage(evidence) -> None:
        nonlocal injected
        if pending.exists() and not injected:
            injected = True
            raise c07.C07CeremonyError(
                "injected host identity change after receipt staging"
            )
        original_assert(evidence)

    monkeypatch.setattr(c07, "_assert_host_freeze_still_valid", reject_after_stage)
    with dedicated_test_database_lease(
        restore_url_value,
        expected_database=TEST_POSTGRES_CONTRACT.restore_database,
        reset=True,
        cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
        passfile=os.environ.get("PGPASSFILE"),
    ), pytest.raises(c07.C07CeremonyError, match="host identity change"):
        run_c07_bigint_ceremony(
            source_engine=engine,
            source_url=source_url,
            restore_engine=restore_engine,
            restore_url=restore_url_value,
            host_evidence=host,
            postgres_data_directory=tmp_path,
            receipt_dir=receipt_dir,
        )
    return injected


def _retry_after_identity_change(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_url: str,
    restore_url_value: str,
    restore_engine: Engine,
    host,
    receipt_dir: Path,
    original_assert,
) -> None:
    monkeypatch.setattr(c07, "_assert_host_freeze_still_valid", original_assert)
    with dedicated_test_database_lease(
        restore_url_value,
        expected_database=TEST_POSTGRES_CONTRACT.restore_database,
        reset=True,
        cluster_identity=os.environ["XPJ_TEST_CLUSTER_IDENTITY"],
        passfile=os.environ.get("PGPASSFILE"),
    ):
        final = run_c07_bigint_ceremony(
            source_engine=engine,
            source_url=source_url,
            restore_engine=restore_engine,
            restore_url=restore_url_value,
            host_evidence=host,
            postgres_data_directory=tmp_path,
            receipt_dir=receipt_dir,
        )
    assert final.is_file()
    assert_c07_lifecycle_ready(engine, receipt_dir=receipt_dir)


def exercise_host_identity_change_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = get_settings().database_url
    receipt_dir = tmp_path / "receipts"
    pending = receipt_dir / f".ticketbox-c07-{CEREMONY_ID}.pending"
    monkeypatch.setattr(backup_service, "_BACKUP_DIR", tmp_path / "backups")
    reset_source_to_c07_base()
    host = isolated_host(tmp_path)
    target_url, restore_engine = new_restore_engine(source_url)
    original_assert = c07._assert_host_freeze_still_valid  # noqa: SLF001
    try:
        injected = _run_identity_change_failure(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            source_url=source_url,
            restore_url_value=target_url,
            restore_engine=restore_engine,
            host=host,
            receipt_dir=receipt_dir,
            pending=pending,
            original_assert=original_assert,
        )
        assert injected is True
        assert not pending.exists()
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == C07_SOURCE_REVISION
            )
        _retry_after_identity_change(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            source_url=source_url,
            restore_url_value=target_url,
            restore_engine=restore_engine,
            host=host,
            receipt_dir=receipt_dir,
            original_assert=original_assert,
        )
    finally:
        restore_engine.dispose()
