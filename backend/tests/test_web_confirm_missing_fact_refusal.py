"""A receipt confirmed before its amount is filled is refused before any commit.

The review draft treats that refusal as final, so the reviewer can check the current
record and keep editing instead of being offered only a replay of the same original.
"""

from __future__ import annotations

import re
from html import unescape

from fastapi.testclient import TestClient

from tests._infra.assets import PNG_BYTES


def _pending(client: TestClient, identity) -> int:
    resp = client.post(f"/u/{identity.upload_key}", headers={"Content-Type": "image/png"}, content=PNG_BYTES)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_confirming_without_an_amount_is_a_final_refusal_the_reviewer_can_edit(
    web_client: TestClient, *, identity
) -> None:
    expense_id = _pending(web_client, identity)
    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=pending")
    assert page.status_code == 200
    scope = re.search(r'name="draft_scope" value="([^"]*)"', page.text)
    key = re.search(r'name="idempotency_key" value="([^"]+)"', page.text)
    assert scope and key
    version = web_client.get(f"/api/expenses/{expense_id}", headers=identity.app_headers).json()["row_version"]
    resp = web_client.post(
        f"/web/expenses/{expense_id}/confirm",
        data={
            "ledger_id": "owner",
            "expected_row_version": str(version),
            "idempotency_key": key.group(1),
            "draft_scope": unescape(scope.group(1)),
            "save_before_confirm": "1",
            "amount_yuan": "",
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code >= 400
    assert resp.json()["error"] == "amount_required"
    assert resp.json()["draft_result"] == "rejected"
