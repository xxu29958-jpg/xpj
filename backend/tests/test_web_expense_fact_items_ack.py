"""A1 Web fact consumer for the existing receipt-items mismatch acknowledgement owner."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.models import LedgerMember
from tests.expense_correction_support import manual_confirmed


def _create_confirmed_items_mismatch(
    client: TestClient, *, identity, setup_key: str
) -> tuple[int, int]:
    expense_id = int(manual_confirmed(client, identity)["id"])
    before = client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()
    corrected = client.post(
        f"/api/expenses/{expense_id}/corrections",
        headers={**identity.app_headers, "Idempotency-Key": setup_key},
        json={
            "expected_row_version": before["row_version"],
            "reason": "补录金额不一致的原小票明细",
            "items": [{"name": "原小票项目", "kind": "product", "amount_cents": 1000}],
        },
    )
    assert corrected.status_code == 201, corrected.text
    return expense_id, int(corrected.json()["expense"]["row_version"])


def _ack_form_html(page_text: str, expense_id: int) -> str | None:
    marker = f'action="/web/expenses/{expense_id}/items/acknowledge-mismatch"'
    if marker not in page_text:
        return None
    marker_index = page_text.index(marker)
    start = page_text.rfind("<form", 0, marker_index)
    end = page_text.index("</form>", marker_index)
    return page_text[start:end]


def test_fact_page_renders_acknowledge_action_for_writer(
    web_client: TestClient, *, identity
) -> None:
    expense_id, row_version = _create_confirmed_items_mismatch(
        web_client, identity=identity, setup_key="fact-ack-render-writer"
    )

    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")

    assert page.status_code == 200, page.text
    form = _ack_form_html(page.text, expense_id)
    assert form is not None
    assert "原小票如此" in form
    assert 'name="csrf_token"' in form
    assert 'name="ledger_id" value="owner"' in form
    assert f'name="expected_row_version" value="{row_version}"' in form


def test_fact_page_hides_acknowledge_action_for_viewer(
    web_client: TestClient, *, identity
) -> None:
    expense_id, _ = _create_confirmed_items_mismatch(
        web_client, identity=identity, setup_key="fact-ack-render-viewer"
    )
    with SessionLocal() as db:
        member = db.scalar(
            select(LedgerMember)
            .where(LedgerMember.ledger_id == "owner")
            .where(LedgerMember.disabled_at.is_(None))
            .limit(1)
        )
        assert member is not None
        member.role = "viewer"
        db.commit()

    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")

    assert page.status_code == 200, page.text
    assert "明细合计与账单金额差" in page.text
    assert _ack_form_html(page.text, expense_id) is None


def test_fact_acknowledge_conflict_stays_on_fact_owner(
    web_client: TestClient, *, identity
) -> None:
    expense_id, row_version = _create_confirmed_items_mismatch(
        web_client,
        identity=identity,
        setup_key="fact-ack-conflict-owner",
    )

    response = web_client.post(
        f"/web/expenses/{expense_id}/items/acknowledge-mismatch",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(row_version - 1),
        },
        follow_redirects=False,
    )

    assert response.status_code == 409, response.text
    assert "账单已在其它端被修改" in response.text
    assert "账单详情" in response.text
    assert f'action="/web/expenses/{expense_id}/save"' not in response.text
    assert _ack_form_html(response.text, expense_id) is not None
