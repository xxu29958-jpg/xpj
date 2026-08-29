"""Expense revision rows are append-only at the PostgreSQL boundary."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from tests.expense_correction_support import idem, manual_confirmed, revision_history


@pytest.mark.real_db
def test_revision_rows_reject_update_and_delete_at_database_boundary(client: TestClient, *, identity) -> None:
    expense = manual_confirmed(client, identity)
    corrected = client.post(
        f"/api/expenses/{expense['id']}/corrections",
        headers=idem(identity.app_headers),
        json={
            "expected_row_version": expense["row_version"],
            "reason": "建立不可篡改历史",
            "merchant": "不可篡改商家",
        },
    )
    assert corrected.status_code == 201, corrected.text
    revision_public_id = corrected.json()["revision"]["public_id"]

    with SessionLocal() as db:
        with pytest.raises(DBAPIError, match="expense_revisions is append-only"):
            db.execute(
                text("UPDATE expense_revisions SET reason = '篡改' WHERE public_id = :public_id"),
                {"public_id": revision_public_id},
            )
            db.commit()
        db.rollback()

    with SessionLocal() as db:
        with pytest.raises(DBAPIError, match="expense_revisions is append-only"):
            db.execute(
                text("DELETE FROM expense_revisions WHERE public_id = :public_id"),
                {"public_id": revision_public_id},
            )
            db.commit()
        db.rollback()

    history = revision_history(client, identity, expense["id"])
    assert history["total"] == 2
    assert history["items"][0]["reason"] == "建立不可篡改历史"
