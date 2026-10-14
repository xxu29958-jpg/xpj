"""Catalog expansion preserves old state; a rollback cannot strand new money."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import engine
from tests._infra.c07_money_migration import reset_schema, run_alembic

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def test_catalog_upgrade_roundtrip_and_minor_unit_fence():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20261012_0001")
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one())
        run_alembic(command.upgrade, "20261014_0001")
        run_alembic(command.downgrade, "20261012_0001")
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one()) == before
        run_alembic(command.upgrade, "20261014_0001")
        change = text("""UPDATE installation_currency_bindings SET state='ACTIVE', home_currency_code='KWD',
            minor_unit_exponent=:digits, rounding_mode='ROUND_HALF_UP', binding_revision=1,
            provenance='OWNER_ADOPTION', evidence_sha256=:hash, activated_at=CURRENT_TIMESTAMP WHERE singleton_id=1""")
        with engine.begin() as db, pytest.raises(DBAPIError, match="ck_installation_currency_binding_shape"):
            db.execute(change, {"digits": 2, "hash": "a" * 64})
        with engine.begin() as db:
            db.execute(change, {"digits": 3, "hash": "a" * 64})
        with pytest.raises(RuntimeError, match="expanded-currency records exist"):
            run_alembic(command.downgrade, "20261012_0001")
        with engine.connect() as db:
            assert db.scalar(text("SELECT minor_unit_exponent FROM installation_currency_bindings")) == 3
    finally:
        reset_schema()
