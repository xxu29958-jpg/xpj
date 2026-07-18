"""Rendered navigation contracts for tertiary Web product pages."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _nav(body: str, class_name: str) -> str:
    match = re.search(
        rf'<nav class="{re.escape(class_name)}"[^>]*>.*?</nav>',
        body,
        re.S,
    )
    assert match is not None, class_name
    return match.group(0)


def test_duplicate_origin_expense_detail_keeps_inbox_navigation(
    web_client: TestClient,
    identity,
) -> None:
    created = web_client.post(
        "/api/expenses/manual",
        headers=identity.app_headers,
        json={
            "amount_cents": 1234,
            "merchant": "重复来源导航测试",
            "category": "其他",
            "expense_time": "2026-07-18T04:00:00Z",
        },
    )
    assert created.status_code == 200, created.text
    expense_id = int(created.json()["id"])

    response = web_client.get(f"/web/expenses/{expense_id}/edit?ledger_id=owner&return_to=duplicates")
    assert response.status_code == 200
    body = response.text
    mobile_primary = _nav(body, "mobile-primary-nav")
    mobile_secondary = _nav(body, "mobile-plan-nav")
    desktop = _nav(body, "desktop-nav")

    assert 'data-domain="inbox"' in body
    assert "返回疑似重复" in body
    assert "/web/duplicates?ledger_id=owner" in body

    for primary in (mobile_primary, desktop):
        assert primary.count('aria-current="location"') == 1
        assert re.search(
            r'class="nav-item active" href="/web/pending\?ledger_id=owner"'
            r'[^>]+aria-current="location"',
            primary,
        )

    for secondary in (mobile_secondary, desktop):
        assert secondary.count('aria-current="page"') == 1
        assert re.search(
            r'class="active" href="/web/duplicates\?ledger_id=owner"'
            r'[^>]+aria-current="page"',
            secondary,
        )
