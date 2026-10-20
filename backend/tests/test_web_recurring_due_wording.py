"""A fixed expense whose expected date has passed says so instead of calling it the next one due.

Paid periods are skipped when the due date is computed, so a due date before
today means this period still has no linked payment. The page used to show it
as "下一笔到期 · 宽带 … 2026-10-15" on 2026-10-20.
"""

from __future__ import annotations

import pytest

from app.routes.web_common import templates
from tests.test_web_recurring_history_view import listing_context


def _render(today: str | None) -> str:
    ctx = listing_context("active", True)
    ctx["draft_public_id"] = None  # the listing, not the item's open editor
    ctx["hero"] = {"active_count": 1, "monthly_total_yuan": "1200",
        "next_due": {"merchant": "原日元计划", "date": "2026-05-08", "home_currency_code": "JPY", "amount_yuan": "1200"}}
    if today is not None:
        ctx["recurring_today"] = today
    return templates.get_template("recurring.html").render(**ctx)


def test_a_passed_expected_date_is_shown_as_an_unrecorded_period() -> None:
    body = _render("2026-05-20")
    assert "已过预计日 · 原日元计划" in body and "下一笔到期" not in body
    assert "预计 2026-05-08 已过，本期还没有对应付款" in body and "下次预计 2026-05-08" not in body


@pytest.mark.parametrize("today", ["2026-05-08", "2026-05-01", None])
def test_today_or_a_future_date_keeps_the_next_due_wording(today: str | None) -> None:
    body = _render(today)
    assert "下一笔到期 · 原日元计划" in body and "已过预计日" not in body
    assert "下次预计 2026-05-08" in body and "已过，本期" not in body
