"""Batch undo coverage for /web pending review actions."""

from __future__ import annotations

from api_contract_helpers import web_save_expense
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Expense, LedgerAuditLog


def _create_pending(client: TestClient, *, identity) -> int:
    """Upload a tiny PNG to the owner ledger so /web/pending sees it."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/u/{identity.upload_key}",
        headers={"Content-Type": "image/png"},
        content=png,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def _seed_pending_with_amount(
    web_client: TestClient,
    amount_yuan: str,
    merchant: str,
    *,
    identity,
) -> int:
    expense_id = _create_pending(web_client, identity=identity)
    resp = web_save_expense(
        web_client,
        expense_id,
        identity=identity,
        data={
            "amount_yuan": amount_yuan,
            "merchant": merchant,
            "category": "其他",
            "note": "",
            "ledger_id": "owner",
        },
    )
    assert resp.status_code in {303, 307}, resp.text
    return expense_id


def test_web_batch_reject_redirect_renders_batch_undo_form(
    web_client: TestClient, *, identity
) -> None:
    first = _seed_pending_with_amount(web_client, "12.00", "Undo A", identity=identity)
    second = _seed_pending_with_amount(web_client, "13.00", "Undo B", identity=identity)
    resp = web_client.post(
        "/web/pending/batch-reject",
        data={
            "ledger_id": "owner",
            "expense_ids": [str(first), str(second)],
            "filter": "all",
        },
        follow_redirects=False,
    )
    assert resp.status_code in {303, 307}, resp.text
    location = resp.headers["location"]
    assert "undo_id=" in location
    assert "undo_rv=" in location

    page = web_client.get(location)
    assert page.status_code == 200, page.text
    assert 'action="/web/pending/batch-undo"' in page.text
    assert f'name="expense_ids" value="{first}"' in page.text
    assert f'name="expense_ids" value="{second}"' in page.text
    assert page.text.count('name="expected_row_version"') == 2


def test_web_batch_undo_restores_rejected_rows_and_writes_audit(
    web_client: TestClient, *, identity
) -> None:
    first = _seed_pending_with_amount(
        web_client, "12.00", "Undo Apply A", identity=identity
    )
    second = _seed_pending_with_amount(
        web_client, "13.00", "Undo Apply B", identity=identity
    )
    reject = web_client.post(
        "/web/pending/batch-reject",
        data={
            "ledger_id": "owner",
            "expense_ids": [str(first), str(second)],
            "filter": "all",
            "fragment": "1",
        },
        follow_redirects=False,
    )
    assert reject.status_code == 200, reject.text
    undo_items = reject.json()["undo_items"]

    undo = web_client.post(
        "/web/pending/batch-undo",
        data={
            "ledger_id": "owner",
            "expense_ids": [str(item["id"]) for item in undo_items],
            "expected_row_version": [
                str(item["expected_row_version"]) for item in undo_items
            ],
        },
        follow_redirects=False,
    )
    assert undo.status_code in {303, 307}, undo.text
    assert "flash_type=success" in undo.headers["location"]

    with SessionLocal() as db:
        rows = list(db.scalars(select(Expense).where(Expense.id.in_([first, second]))))
        assert {row.id: row.status for row in rows} == {first: "pending", second: "pending"}
        audits = list(
            db.scalars(
                select(LedgerAuditLog)
                .where(LedgerAuditLog.action == "undo")
                .where(LedgerAuditLog.resource_type == "expense")
            )
        )
        assert len(audits) >= 2
