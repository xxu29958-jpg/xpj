"""A funds task's save status sits beside the action that changed, not under the sticky bar.

After a stale or refused submission the page reloads at the top and the
primary action becomes "核实原资金任务"; the only explanation was a small hint
below the form, hidden behind the sticky action bar on a phone. The status
now lives in that bar, after its buttons, hidden until there is something to say.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from app.middleware.csrf import CSRF_COOKIE_NAME
from app.routes.web_auth import SESSION_COOKIE_NAME
from tests._local_web_identity_support import _connect_local_session, installed_web_setup
from tests._web_native_form_support import hidden_post_forms


class _StatusPlacement(HTMLParser):
    """Record whether the draft-status element is inside the task action bar, and after its last button."""

    def __init__(self, attribute: str) -> None:
        super().__init__()
        self.attribute, self.depth, self.bar_depth = attribute, 0, None
        self.found: dict[str, object] | None = None
        self.buttons_after = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "div":
            self.depth += 1
            if "product-task-actions" in (values.get("class") or "").split():
                self.bar_depth = self.depth
        if self.attribute in values:
            self.found = {"in_bar": self.bar_depth is not None, "hidden": "hidden" in values, "role": values.get("role")}
        elif self.found and self.bar_depth is not None and tag in {"button", "a"}:
            self.buttons_after += 1

    def handle_endtag(self, tag):
        if tag == "div":
            if self.depth == self.bar_depth:
                self.bar_depth = None
            self.depth -= 1


def _placement(html: str, attribute: str) -> dict[str, object]:
    parser = _StatusPlacement(attribute)
    parser.feed(html)
    assert parser.found is not None, f"{attribute} missing"
    return {**parser.found, "buttons_after": parser.buttons_after}


@pytest.fixture()
def installed_funds_web():
    yield from installed_web_setup()


@pytest.mark.currency_binding_unbound
def test_funds_and_envelope_status_lives_in_the_action_bar(installed_funds_web) -> None:
    installed = installed_funds_web
    token = _connect_local_session(installed, next_url="/web/funds")
    cookie = f"{SESSION_COOKIE_NAME}={token}"
    page = installed.browser.get("/web/funds?task=create", headers={"Cookie": cookie})
    headers = {"Cookie": f"{cookie}; {CSRF_COOKIE_NAME}={page.cookies.get(CSRF_COOKIE_NAME)}",
        "Origin": "http://127.0.0.1:8000", "Accept": "application/json"}
    expected = {"in_bar": True, "hidden": True, "role": "status", "buttons_after": 0}
    assert _placement(page.text, "data-funds-draft-status") == expected

    fields = hidden_post_forms(page.text)["/web/funds/save"]
    fields.update(name="生活卡", kind="bank", currency_code="CNY", opening_amount="100", visibility="private",
        opening_source="本人对账", occurred_on="2026-10-18", institution="", tail="")
    created = installed.browser.post("/web/funds/save", data=fields, headers=headers)
    assert created.status_code == 200, created.text
    account = created.json()["receipt"]["public_id"]
    income = installed.browser.get(f"/web/funds?task=income&account_id={account}", headers=headers)
    assert income.status_code == 200, income.text
    assert _placement(income.text, "data-funds-draft-status") == expected

    envelopes = installed.browser.get("/web/envelopes", headers=headers)
    assert envelopes.status_code == 200, envelopes.text
    assert _placement(envelopes.text, "data-envelope-draft-status") == expected
