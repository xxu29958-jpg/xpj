"""Only the explicit next ACTIVE revision is added to the SQL transition fence."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import engine

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20260909_0004"
_HEAD = "20260909_0005"


def test_default_migration_preserves_adoption_and_rejects_other_state_mutations():
    from tests._infra.c07_money_migration import reset_schema, run_alembic

    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        with engine.begin() as db:
            db.execute(text("""UPDATE installation_currency_bindings SET state='ACTIVE', home_currency_code='CNY',
                minor_unit_exponent=2, rounding_mode='ROUND_HALF_UP', binding_revision=1, provenance='OWNER_ADOPTION',
                evidence_sha256=:evidence, activated_at=CURRENT_TIMESTAMP WHERE singleton_id=1"""), {"evidence": "a" * 64})
            before = dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one())
        run_alembic(command.upgrade, _HEAD)
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one()) == before
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority")) == _HEAD
        for forbidden in ("binding_revision=2", "home_currency_code='JPY', minor_unit_exponent=0",
            "home_currency_code='JPY', minor_unit_exponent=0, binding_revision=3, provenance='OWNER_DEFAULT_CHANGE'",
            "home_currency_code='JPY', minor_unit_exponent=0, binding_revision=2, provenance='OWNER_ADOPTION'",
            "home_currency_code='JPY', minor_unit_exponent=0, binding_revision=2, provenance='OWNER_DEFAULT_CHANGE', currency_contract_version=2"):
            with engine.begin() as db, pytest.raises(DBAPIError, match="invalid state transition"):
                db.execute(text(f"UPDATE installation_currency_bindings SET {forbidden} WHERE singleton_id=1"))
        with engine.begin() as db:
            db.execute(text("""UPDATE installation_currency_bindings SET home_currency_code='JPY', minor_unit_exponent=0,
                binding_revision=2, provenance='OWNER_DEFAULT_CHANGE', updated_at=CURRENT_TIMESTAMP WHERE singleton_id=1"""))
        with pytest.raises(RuntimeError, match="cannot erase accepted default currency changes"):
            run_alembic(command.downgrade, _PARENT)
    finally:
        reset_schema()


def test_unused_default_change_migration_can_downgrade_without_rewriting_binding():
    from tests._infra.c07_money_migration import reset_schema, run_alembic

    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        with engine.connect() as db:
            before = dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one())
        run_alembic(command.upgrade, _HEAD)
        run_alembic(command.downgrade, _PARENT)
        with engine.connect() as db:
            assert dict(db.execute(text("SELECT * FROM installation_currency_bindings")).mappings().one()) == before
    finally:
        reset_schema()
