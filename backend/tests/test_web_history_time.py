"""Saved-history times read in the accounting timezone, like every other record time.

Goal, budget, fixed-expense, income-plan, rule and envelope histories rendered
"2026-10-19 07:46:37 UTC" while the debt pages showed the same instant as
"2026-10-19 15:46". The visible time now uses the shared accounting label;
the exact UTC instant stays on the ``<time>`` element.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.routes.web_common import templates
from app.services import budget_history_service, spending_contract_service
from tests._web_budget_test_support import _save_budget


@pytest.mark.parametrize(("zone", "expected"), [
    ("Asia/Shanghai", "2026-10-20 07:46"),
    ("America/Los_Angeles", "2026-10-19 16:46"),
])
def test_saved_time_uses_persisted_ledger_zone_after_installation_default_changes(
    web_client, identity, monkeypatch, zone, expected,
) -> None:
    instant = datetime(2026, 10, 19, 23, 46, 37, tzinfo=UTC)
    monkeypatch.setattr(budget_history_service, "now_utc", lambda: instant)
    path = "/api/ledgers/owner/calendar"
    rule = web_client.get(path, headers=identity.app_headers).json()
    changed = web_client.post(path, headers={**identity.app_headers, "Idempotency-Key": "history-zone"},
        json={"expected_revision": rule["revision"], "timezone_name": zone})
    assert changed.status_code == 200, changed.text
    _save_budget(web_client)
    expected_time = f'<time datetime="2026-10-19T23:46:37Z" title="2026-10-19T23:46:37Z">{expected}</time>'
    for installation_zone in ("UTC", "Pacific/Honolulu"):
        monkeypatch.setattr(spending_contract_service, "get_settings",
            lambda zone=installation_zone: SimpleNamespace(ocr_default_timezone=zone))
        page = web_client.get("/web/budgets/history", params={"ledger_id": "owner", "month": "2026-05"})
        assert page.status_code == 200, page.text
        assert expected_time in page.text
        assert "建立预算" in page.text and "¥1,000.00" in page.text


def test_saved_time_without_a_ledger_rule_explicitly_keeps_utc() -> None:
    instant = datetime(2026, 10, 19, 23, 46, 37, tzinfo=UTC)
    rendered = templates.env.from_string(
        "{% from '_history_time.html' import saved_time %}{{ saved_time(value) }}").render(value=instant).strip()
    assert rendered == ('<time datetime="2026-10-19T23:46:37Z" title="2026-10-19T23:46:37Z">'
        '2026-10-19 23:46:37 UTC</time>')
