"""Product-flow gates for confirmed fact return context and recovery."""

from __future__ import annotations

import re
from html import unescape

from fastapi.testclient import TestClient

from tests.web_expense_fact_test_support import create_confirmed


def _hidden_input(body: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', body)
    assert match is not None, name
    return unescape(match.group(1))


def test_confirmed_fact_direct_entry_returns_to_confirmed_stream(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)

    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")

    assert page.status_code == 200, page.text
    match = re.search(
        r'<a\b[^>]*href="([^"]+)"[^>]*>\s*返回已确认流水\s*</a>',
        page.text,
    )
    assert match is not None
    assert unescape(match.group(1)) == "/web/confirmed?ledger_id=owner"


def test_correction_blank_reason_keeps_draft_and_return_context(
    web_client: TestClient,
    *,
    identity,
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)
    form = web_client.get(
        f"/web/expenses/{expense_id}/correct",
        params={
            "ledger_id": "owner",
            "return_to": "search",
            "return_query": "上下文咖啡",
        },
    )
    assert form.status_code == 200, form.text

    response = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "",
            "merchant": "想改但没写原因",
            "expected_row_version": _hidden_input(form.text, "expected_row_version"),
            "idempotency_key": _hidden_input(form.text, "idempotency_key"),
            "return_to": _hidden_input(form.text, "return_to"),
            "return_query": _hidden_input(form.text, "return_query"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "请说明这次更正的原因" in response.text
    assert "想改但没写原因" in response.text
    assert _hidden_input(response.text, "return_to") == "search"
    assert _hidden_input(response.text, "return_query") == "上下文咖啡"
