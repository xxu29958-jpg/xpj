"""Legacy corrections recover identity without inventing a reviewed source version."""

import hashlib

import pytest
from alembic import command
from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import RepaymentDraft
from app.services.currency_binding_service import resolve_write_capability
from tests._infra.alembic_runtime import alembic_config_for_test, run_alembic_for_test
from tests.debt_proposal_helpers import capture_repayment_draft
from tests.expense_correction_support import manual_confirmed

pytestmark = pytest.mark.real_db


def test_legacy_source_is_recovered_without_authorizing_automatic_reversal(client, identity):
    expense = manual_confirmed(client, identity, amount_cents=3790)
    capture = capture_repayment_draft(client, identity, source="other", amount_cents=3790)
    with SessionLocal.begin() as db:
        resolve_write_capability(db)
        draft = db.scalar(select(RepaymentDraft).where(RepaymentDraft.public_id == capture["public_id"]))
        material = f"repayment_expense|{draft.tenant_id}|{draft.created_by_account_id}|{expense['public_id']}"
        draft.draft_idempotency_key = hashlib.sha256(material.encode()).hexdigest()
    config = alembic_config_for_test()
    try:
        run_alembic_for_test(engine, config, command.downgrade, "20261015_0001")
        run_alembic_for_test(engine, config, command.upgrade, "head")
        response = client.get(f"/api/repayment-drafts/{capture['public_id']}", headers=identity.app_headers)
        assert response.status_code == 200, response.text
        assert response.json()["source_expense_public_id"] == expense["public_id"]
        assert response.json()["source_expense_requires_review"] is True
        fresh = client.post(f"/api/expenses/{expense['id']}/repayment-draft", headers=identity.app_headers,
            json={"expected_row_version": expense["row_version"]})
        assert fresh.status_code == 201, fresh.text
        assert fresh.json()["public_id"] != capture["public_id"]
        assert fresh.json()["source_expense_requires_review"] is False
    finally:
        run_alembic_for_test(engine, config, command.upgrade, "head")
