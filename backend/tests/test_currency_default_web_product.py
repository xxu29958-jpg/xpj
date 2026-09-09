"""Actual paired Desktop, native forms and PostgreSQL default-change receipts."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Goal, InstallationCurrencyAuditLog, InstallationCurrencyBinding
from tests._web_native_form_support import hidden_post_forms
from tests.test_currency_adoption_product import _AdoptionBrowser
from tests.test_currency_adoption_product import adoption_browser as adoption_browser

pytestmark = [pytest.mark.currency_binding_unbound, pytest.mark.real_db]


@pytest.mark.parametrize("adoption_browser", ["EMPTY"], indirect=True)
def test_native_default_change_replays_its_original_result_and_preserves_recorded_money(adoption_browser: _AdoptionBrowser):
    browser = adoption_browser
    entry = "/web/currency-adoption"
    page = browser.client.get(entry, headers=browser.headers)
    fields = hidden_post_forms(page.text)[entry]
    adopted = browser.client.post(entry, headers=browser.headers,
        data={**fields, "home_currency_code": "JPY"}, follow_redirects=False)
    assert adopted.status_code == 303, adopted.text
    goal_page = browser.client.get("/web/goals", headers=browser.headers)
    goal_created = browser.client.post("/web/goals/create", headers=browser.headers,
        data={**hidden_post_forms(goal_page.text)["/web/goals/create"], "name": "保留原日元目标",
            "target_amount_yuan": "1000", "month": "2026-09"}, follow_redirects=False)
    assert goal_created.status_code == 303, goal_created.text
    assert 'href="/web/currency-adoption"' in goal_page.text

    editor = browser.client.get(entry + "?change=true", headers=browser.headers)
    path = entry + "/change"
    original = {**hidden_post_forms(editor.text)[path], "home_currency_code": "USD", "reason": "以后主要使用美元"}
    accepted = browser.client.post(path, headers=browser.headers, data=original)
    assert accepted.status_code == 200, accepted.text
    next_editor = browser.client.get(entry + "?change=true", headers=browser.headers)
    next_fields = hidden_post_forms(next_editor.text)[path]
    assert next_fields["source_home_currency_code"] == "USD"
    later = browser.client.post(path, headers=browser.headers,
        data={**next_fields, "home_currency_code": "EUR", "reason": "迁往欧元区"})
    assert later.status_code == 200, later.text
    replay = browser.client.post(path, headers=browser.headers, data=original)
    assert replay.status_code == 200 and replay.text == accepted.text

    with SessionLocal() as db:
        goal = db.scalar(select(Goal).where(Goal.name == "保留原日元目标"))
        assert goal is not None and (goal.home_currency_code, goal.target_amount_cents) == ("JPY", 1000)
        assert db.get(InstallationCurrencyBinding, 1).home_currency_code == "EUR"
        events = list(db.scalars(select(InstallationCurrencyAuditLog).where(
            InstallationCurrencyAuditLog.action == "OWNER_DEFAULT_CHANGE")))
        assert len(events) == 2
