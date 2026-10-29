"""The shipped migration runner preserves old facts/intents and adopts the new generation."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, text

from app.database import SessionLocal, engine
from app.models import Account, DebtBillCapture
from app.services.file_service import resolve_upload_path_for_tenant, save_upload_bytes
from scripts.build_database_generation_program import compile_program
from tests._infra.assets import PNG_BYTES
from tests._infra.c07_money_migration import reset_schema, run_alembic, seed_owner
from tests._infra.c07_money_protocol_probe import run_database_generation_upgrade
from tests._infra.currency import activate_test_currency_authority

pytestmark = [pytest.mark.real_db, pytest.mark.currency_binding_unbound]


def _snapshot():
    with engine.connect() as db:
        return {table: list(db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings())
                for table in ("expenses", "api_idempotency_keys")}


def test_debt_bill_migration_preserves_original_data_and_refuses_evidence_downgrade():
    reset_schema()
    try:
        run_alembic(command.upgrade, "20261023_0002")
        seed_owner()
        with SessionLocal.begin() as db:
            activate_test_currency_authority(db, "CNY")
            saved = save_upload_bytes(PNG_BYTES, tenant_id="owner", filename="old.png", content_type="image/png")
            original = resolve_upload_path_for_tenant(saved.relative_path, "owner")
            db.execute(text("""INSERT INTO expenses (public_id, tenant_id, merchant, category, source,
                amount_cents, original_amount_minor, original_currency_code, home_currency_code, image_path, image_hash,
                duplicate_status, status, created_at, updated_at, row_version, fact_revision)
                VALUES (:id, 'owner', 'Old shop', '其他', 'manual', 1250, 1250, 'CNY', 'CNY', :path, :hash,
                'none', 'confirmed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 7, 3)"""),
                {"id": str(uuid4()), "path": saved.relative_path, "hash": saved.image_hash})
            db.execute(text("""INSERT INTO api_idempotency_keys (tenant_id, idempotency_key, operation,
                request_fingerprint, target_type, target_id, status, response_body, created_at, expires_at)
                VALUES ('owner', 'accepted-old-key', 'create_debt', :hash, 'debt', 'accepted-old-key', 'succeeded',
                    CAST(:receipt AS JSONB), CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP + INTERVAL '1 day')"""), {"hash": "1" * 64,
                    "receipt": '{"old":"unchanged receipt","principal_amount_cents":1250}'})
        before, bytes_before = _snapshot(), original.read_bytes()
        run_database_generation_upgrade("20261023_0002", "20261028_0001")
        assert _snapshot() == before and original.read_bytes() == bytes_before
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261028_0001"
            assert db.scalar(text("SELECT schema_revision FROM dataset_authority WHERE singleton_id=1")) == "20261028_0001"
        program = compile_program(Path(__file__).resolve().parents[1])
        step = next(item for item in program["revisions"] if item["revision"] == "20261028_0001")
        assert step["postcondition"] == "assert_postcondition"
        module = Path(__file__).resolve().parents[1] / step["module_path"]
        assert hashlib.sha256(module.read_bytes()).hexdigest() == step["module_sha256"]
        # Empty-schema downgrade is legitimate, but a retained new source may never be erased.
        run_alembic(command.downgrade, "20261023_0002")
        assert _snapshot() == before
        run_alembic(command.upgrade, "20261028_0001")
        with SessionLocal.begin() as db:
            owner = db.scalar(select(Account.id).order_by(Account.id))
            db.add(DebtBillCapture(tenant_id="owner", created_by_account_id=owner,
                creation_key="new-create", capture_key="new-capture", request_fingerprint="2" * 64,
                accepted_receipt={"stable": "receipt"}, file_name="old.png", media_type="image/png",
                input_sha256=hashlib.sha256(PNG_BYTES).hexdigest(), image_path=saved.relative_path,
                image_hash=saved.image_hash, image_size_bytes=saved.size_bytes, image_evidence=saved.image_evidence))
        with pytest.raises(RuntimeError, match="cannot erase retained debt-bill"):
            run_alembic(command.downgrade, "20261023_0002")
        assert _snapshot() == before and original.read_bytes() == bytes_before
    finally:
        reset_schema()
