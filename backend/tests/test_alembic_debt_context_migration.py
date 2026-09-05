"""Real PostgreSQL edge: retain old obligations and refuse context-erasing downgrade."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from app.models import Account, Ledger
from app.services.currency_binding_service import resolve_write_capability
from app.services.time_service import now_utc
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db

_PARENT = "20260901_0001"
_HEAD = "20260905_0001"


def _run(action, revision: str) -> None:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    run_alembic_for_test(engine, config, action, revision)


def _seed_old_debt() -> int:
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        account = Account(display_name="往来迁移用户")
        db.add(account)
        db.flush()
        db.add(Ledger(ledger_id="debt-context-migration", name="往来迁移", owner_account_id=account.id))
        db.flush()
        return db.execute(
            text(
                "INSERT INTO debts (public_id, tenant_id, owner_account_id, created_by_account_id, "
                "direction, counterparty_type, counterparty_label, principal_amount_cents, "
                "home_currency_code, status, source_type, debt_kind, row_version, created_at, updated_at) "
                "VALUES (:public_id, 'debt-context-migration', :actor, :actor, 'i_owe', 'external', "
                "'同行人', 1200, 'CNY', 'open', 'manual', 'one_off', 1, :created_at, :created_at) "
                "RETURNING id"
            ),
            {"public_id": str(uuid4()), "actor": account.id, "created_at": now_utc()},
        ).scalar_one()


def _revision() -> str:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id = 1"))


def test_debt_context_migration_keeps_old_debt_and_refuses_erasure() -> None:
    reset_public_schema(engine)
    try:
        _run(command.upgrade, _PARENT)
        debt_id = _seed_old_debt()
        _run(command.upgrade, _HEAD)
        assert _revision() == _HEAD
        note_column = next(column for column in inspect(engine).get_columns("debts") if column["name"] == "note")
        assert note_column["nullable"] is True
        with engine.connect() as connection:
            old = connection.execute(
                text("SELECT note, principal_amount_cents, row_version FROM debts WHERE id = :id"),
                {"id": debt_id},
            ).one()
        assert tuple(old) == (None, 1200, 1)

        _run(command.downgrade, _PARENT)
        assert _revision() == _PARENT
        assert "note" not in {column["name"] for column in inspect(engine).get_columns("debts")}
        _run(command.upgrade, _HEAD)
        with SessionLocal.begin() as db:
            resolve_write_capability(db)
            db.execute(text("UPDATE debts SET note = '出差垫款' WHERE id = :id"), {"id": debt_id})
        with pytest.raises(RuntimeError, match="Debt context exists"):
            _run(command.downgrade, _PARENT)
        assert _revision() == _HEAD
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT note FROM debts WHERE id = :id"), {"id": debt_id}) == "出差垫款"
    finally:
        reset_public_schema(engine)
