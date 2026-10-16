"""Shared preparation for the existing spending goal consumers."""

from __future__ import annotations

import re
from html import unescape
from uuid import uuid4

from fastapi.testclient import TestClient

from tests._runtime_protocol import negotiated_headers
from tests._web_native_form_support import hidden_post_forms


def _goal(client: TestClient, identity, *, home_currency_code: str = "CNY", amount_minor: int = 20000) -> dict:
    response = client.post("/api/goals", headers={**negotiated_headers(client, identity.app_headers), "Idempotency-Key": str(uuid4())}, json={
        "home_currency_code": home_currency_code,
        "name": "原消费目标", "month": "2026-05", "category": "餐饮", "target_amount_cents": amount_minor,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _editor(client: TestClient, public_id: str, *, include_archived: bool = False) -> tuple[str, dict[str, str]]:
    action = f"/web/goals/{public_id}/edit"
    listing = client.get("/web/goals", params={"ledger_id": "owner", "month": "2026-05", "include_archived": include_archived})
    assert listing.status_code == 200, listing.text
    href = next(unescape(href) for href in re.findall(r'<a[^>]*href="([^"]+)"', listing.text) if href.startswith(action + "?"))
    response = client.get(href)
    assert response.status_code == 200, response.text
    fields = hidden_post_forms(response.text)[action]
    assert fields["idempotency_key"]
    assert int(fields["expected_row_version"]) > 0
    return action, fields
