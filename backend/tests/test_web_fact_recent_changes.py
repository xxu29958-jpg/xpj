"""Fact page 最近变更: each entry says its kind once; a correction keeps its own reason."""

from __future__ import annotations

import re
from html import unescape

from fastapi.testclient import TestClient

from tests.web_expense_fact_test_support import create_confirmed, row_version


def _recent_lines(body: str) -> list[str]:
    section = re.search(r'<section class="fact-recent".*?</section>', body, re.S)
    assert section is not None
    return [
        unescape(" ".join(line.split())) for line in re.findall(r'<p class="meta">(.*?)</p>', section.group(0), re.S)
    ]


def test_recent_changes_name_the_first_confirmation_once_and_keep_correction_reasons(
    web_client: TestClient, *, identity
) -> None:
    expense_id = create_confirmed(web_client, identity=identity)

    page = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner")
    assert page.status_code == 200
    [confirmed] = _recent_lines(page.text)
    assert confirmed.startswith("首次确认 · ")
    assert confirmed.count("首次确认") == 1

    form = web_client.get(f"/web/expenses/{expense_id}/correct?ledger_id=owner")
    key = re.search(r'name="idempotency_key" value="([^"]*)"', form.text)
    assert key is not None
    resp = web_client.post(
        f"/web/expenses/{expense_id}/corrections",
        data={
            "ledger_id": "owner",
            "reason": "小票商家看错了",
            "merchant": "更正后的商家",
            "expected_row_version": str(row_version(web_client, expense_id, identity)),
            "idempotency_key": unescape(key.group(1)),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text

    corrected, first = _recent_lines(web_client.get(resp.headers["location"]).text)
    assert corrected.startswith("更正 · ")
    assert corrected.endswith(" · 小票商家看错了")
    assert first.count("首次确认") == 1
