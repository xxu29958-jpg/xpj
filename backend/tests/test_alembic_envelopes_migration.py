"""One real migration edge: empty rollback works, saved cash purposes cannot vanish."""
from importlib import import_module

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_envelope_migration_retains_saved_intent_and_currency():
    parent, head = "20261018_0004", "20261019_0001"
    reset_schema()
    try:
        run_alembic(command.upgrade, parent)
        actor, _ = seed_owner()
        run_alembic(command.upgrade, head)
        migration = import_module("migrations.versions.20261019_0001_cash_envelopes")
        with engine.connect() as db:
            migration.assert_postcondition(db)
            assert db.scalar(text("SELECT count(*) FROM envelope_books")) == 0
        run_alembic(command.downgrade, parent)
        run_alembic(command.upgrade, head)
        with SessionLocal.begin() as db:
            db.execute(text("INSERT INTO envelope_books VALUES ('owner','KWD',1,CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO envelope_allocations VALUES ('owner','2026-10','savings',12345)"))
            db.execute(text("INSERT INTO envelope_revisions VALUES ('owner',1,:actor,'2026-10','已核对分配',"
                            "CAST(:snapshot AS JSON),CURRENT_TIMESTAMP)"),
                       {"actor": actor, "snapshot": '{"home_currency_code":"KWD","allocations":{"savings":12345}}'})
        for statement in ("UPDATE envelope_books SET home_currency_code='CNY'",
                          "UPDATE envelope_allocations SET allocated_minor=-1",
                          "DELETE FROM envelope_revisions", "TRUNCATE envelope_revisions"):
            with SessionLocal.begin() as db, pytest.raises(DBAPIError):
                db.execute(text(statement))
        with pytest.raises(RuntimeError, match="downgrade refused"):
            run_alembic(command.downgrade, parent)
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == head
            assert db.execute(text("SELECT home_currency_code, allocated_minor FROM envelope_books "
                                   "JOIN envelope_allocations USING (tenant_id)")).one() == ("KWD", 12345)
    finally:
        reset_schema()
