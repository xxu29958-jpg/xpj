"""The original audit survives the reason-field edge; recorded reasons cannot be erased."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import engine
from tests._infra.alembic_runtime import reset_public_schema, run_alembic_for_test

pytestmark = pytest.mark.real_db


def test_rule_reason_migration_retains_old_batch_and_refuses_recorded_reason_erasure():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    def migrate(action, revision):
        run_alembic_for_test(engine, config, action, revision)
    reset_public_schema(engine)
    try:
        migrate(command.upgrade, "20261014_0001")
        with engine.begin() as db:
            account_id = db.execute(text("INSERT INTO accounts (public_id, display_name, created_at) "
                "VALUES (:id, 'Reason owner', CURRENT_TIMESTAMP) RETURNING id"), {"id": str(uuid4())}).scalar_one()
            db.execute(text("INSERT INTO ledgers (ledger_id, name, owner_account_id, created_at) "
                "VALUES ('reason-ledger', 'Reason test', :owner, CURRENT_TIMESTAMP)"), {"owner": account_id})
            batch_id = db.execute(text("INSERT INTO rule_application_batches "
                "(public_id, tenant_id, status, pending_scanned, changed_count, created_at) "
                "VALUES (:id, 'reason-ledger', 'applied', 7, 3, CURRENT_TIMESTAMP) RETURNING id"), {"id": str(uuid4())}).scalar_one()
        migrate(command.upgrade, "20261015_0001")
        with engine.connect() as db:
            assert tuple(db.execute(text("SELECT changed_count, application_reason, rollback_reason "
                "FROM rule_application_batches WHERE id=:id"), {"id": batch_id}).one()) == (3, None, None)
        migrate(command.downgrade, "20261014_0001")
        assert "application_reason" not in {column["name"] for column in inspect(engine).get_columns("rule_application_batches")}
        migrate(command.upgrade, "20261015_0001")
        with engine.begin() as db:
            db.execute(text("UPDATE rule_application_batches SET application_reason=:apply, rollback_reason=:undo WHERE id=:id"),
                {"id": batch_id, "apply": "按商家统一分类", "undo": "核对后撤回本批次"})
        with pytest.raises(RuntimeError, match="cannot erase retained rule application reasons"):
            migrate(command.downgrade, "20261014_0001")
        with engine.connect() as db:
            assert db.scalar(text("SELECT rollback_reason FROM rule_application_batches WHERE id=:id"), {"id": batch_id}) == "核对后撤回本批次"
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == "20261015_0001"
    finally:
        reset_public_schema(engine)
