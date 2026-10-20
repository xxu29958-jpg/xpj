"""Review input the server refuses before any commit is a final refusal.

The review draft then offers to check the current record and keep editing, instead of
only replaying the same original or discarding what the reviewer already typed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models import Expense
from app.services.time_service import now_utc
from tests._infra.assets import PNG_BYTES
from tests.test_web_expense_detail_v1_slice import _owner_member_id, _seed_pending_expense


def _row_version(client: TestClient, identity, expense_id: int) -> str:
    return str(client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["row_version"])


def _refusal(resp) -> tuple[str, str]:
    assert resp.status_code >= 400, resp.text
    return resp.json()["error"], resp.json()["draft_result"]


def test_confirming_without_an_amount_is_a_final_refusal(web_client: TestClient, *, identity) -> None:
    upload = web_client.post(f"/u/{identity.upload_key}", headers={"Content-Type": "image/png"}, content=PNG_BYTES)
    assert upload.status_code == 200, upload.text
    expense_id = int(upload.json()["id"])
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=pending")
    scope = re.search(r'name="draft_scope" value="([^"]*)"', page.text)
    key = re.search(r'name="idempotency_key" value="([^"]+)"', page.text)
    assert scope and key
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "idempotency_key": key.group(1),
            "draft_scope": unescape(scope.group(1)),
            "save_before_confirm": "1",
            "amount_yuan": "",
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == ("amount_required", "rejected")


def test_family_shares_above_the_bill_are_a_final_refusal(web_client: TestClient, *, identity) -> None:
    expense_id = _seed_pending_expense(amount_cents=5000)
    resp = web_client.post(
        f"/web/expenses/{expense_id}/splits/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "split_member_id": [str(_owner_member_id())],
            "split_amount_yuan": ["80.00"],
            "split_note": [""],
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == ("expense_split_total_exceeds_parent", "rejected")


@pytest.mark.parametrize("rate", ["0", "0.047826123456"])
def test_an_unusable_manual_rate_is_a_final_refusal(web_client: TestClient, *, identity, rate: str) -> None:
    with SessionLocal() as db:
        now = now_utc()
        expense = Expense(
            tenant_id="owner",
            amount_cents=None,
            home_currency_code="CNY",
            original_currency_code="JPY",
            original_amount_minor=1200,
            merchant="东京便利店",
            category="餐饮",
            note="",
            source="manual",
            raw_text="",
            status="pending",
            fx_status="pending",
            expense_time=datetime(2026, 5, 4, 1, 0, tzinfo=UTC),
            created_at=now,
            updated_at=now,
        )
        db.add(expense)
        db.commit()
        expense_id = expense.id
    resp = web_client.post(
        f"/web/expenses/{expense_id}/save",
        data={
            "ledger_id": "owner",
            "expected_row_version": _row_version(web_client, identity, expense_id),
            "amount_yuan": "1200",
            "original_currency": "JPY",
            "manual_exchange_rate": rate,
            "merchant": "东京便利店",
            "category": "餐饮",
        },
        headers={"Accept": "application/json"},
    )
    assert _refusal(resp) == ("exchange_rate_invalid", "rejected")
