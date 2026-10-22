"""Real PostgreSQL preserves old OCR facts and refuses loss of new image evidence."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.database import SessionLocal, engine
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]
_PARENT = "20261019_0005"
_HEAD = "20261021_0001"


def _snapshot():
    with engine.connect() as db:
        return dict(db.execute(text("SELECT * FROM ocr_facts")).mappings().one())


def test_evidence_edge_preserves_exact_old_fact_and_refuses_erasure():
    reset_schema()
    try:
        run_alembic(command.upgrade, _PARENT)
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            expense_id = db.scalar(text("""
                INSERT INTO expenses (public_id, tenant_id, merchant, category, source,
                    duplicate_status, status, created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'owner', 'Old shop', '其他', 'manual', 'none', 'pending',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1) RETURNING id
            """), {"id": str(uuid4())})
            db.execute(text("""
                INSERT INTO ocr_facts (public_id, tenant_id, expense_id, ocr_provider,
                    raw_text, parsed_merchant, extracted_at, created_at)
                VALUES (:id, 'owner', :expense, 'rapidocr', 'Old shop 10.00', 'Old shop',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """), {"id": str(uuid4()), "expense": expense_id})
        old = _snapshot()
        run_alembic(command.upgrade, _HEAD)
        after = _snapshot()
        assert after.pop("evidence_json") is None
        assert after == old
        run_alembic(command.downgrade, _PARENT)
        assert _snapshot() == old
        assert "evidence_json" not in {item["name"] for item in inspect(engine).get_columns("ocr_facts")}
        run_alembic(command.upgrade, _HEAD)
        evidence = '{"schema":"text-blocks/v1","input_sha256":"frozen","blocks":[]}'
        with SessionLocal.begin() as db:
            db.execute(text("UPDATE ocr_facts SET evidence_json=:evidence"), {"evidence": evidence})
        before = _snapshot()
        with pytest.raises(RuntimeError, match="OCR image evidence exists"):
            run_alembic(command.downgrade, _PARENT)
        assert _snapshot() == before
        with engine.connect() as db:
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == _HEAD
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == _HEAD
    finally:
        reset_schema()
