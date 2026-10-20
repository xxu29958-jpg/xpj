"""Saved-history times read in the accounting timezone, like every other record time.

Goal, budget, fixed-expense, income-plan, rule and envelope histories rendered
"2026-10-19 07:46:37 UTC" while the debt pages showed the same instant as
"2026-10-19 15:46". The visible time now uses the shared accounting label;
the exact UTC instant stays on the ``<time>`` element.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.routes.web_common import templates
from app.services.spending_contract_service import accounting_datetime_label


def test_saved_time_shows_the_accounting_local_time_and_keeps_the_utc_instant() -> None:
    instant = datetime(2026, 10, 19, 7, 46, 37, tzinfo=UTC)
    rendered = templates.env.from_string(
        "{% from '_history_time.html' import saved_time %}{{ saved_time(value) }}").render(value=instant).strip()
    local = accounting_datetime_label(instant)
    assert rendered == f'<time datetime="2026-10-19T07:46:37Z" title="2026-10-19T07:46:37Z">{local}</time>'
    assert "UTC" not in local and local.startswith("2026-10-19 ")
