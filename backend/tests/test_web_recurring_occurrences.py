"""Actual rendered form -> shared command -> period, budget and reminder."""

import re
from html import unescape

from fastapi.testclient import TestClient

from app.main import app
from app.routes.web_app import _require_local
from tests.test_recurring_occurrences import _create_series, _payment


def _form(body, action):
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, flags=re.S):
        if f'name="action" value="{action}"' in form:
            return {
                name: unescape(value)
                for name, value in re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form)
            }
    raise AssertionError(f"real {action} form is missing")


def test_web_association_and_undo_share_the_api_result(client: TestClient, *, identity) -> None:
    app.dependency_overrides[_require_local] = lambda: None
    try:
        series = _create_series(client, identity)
        payment = _payment(client, identity)
        path = f"/web/recurring/{series['public_id']}/occurrence"
        page = client.get(path, params={"ledger_id": "owner", "month": "2026-09"})
        assert page.status_code == 200, page.text
        original = _form(page.text, "link")
        assert original["expense_public_id"] == payment["public_id"]
        linked = client.post(path, data=original, follow_redirects=False)
        assert linked.status_code == 303, linked.text
        rendered = client.get(linked.headers["location"])
        assert "本期已关联付款" in rendered.text
        assert "2026-10-05" in rendered.text
        api = client.get(
            f"/api/recurring/items/{series['public_id']}/occurrences/2026-09",
            headers=identity.app_headers,
        )
        assert api.json()["reserved_amount_cents"] == 0
        cleared = client.post(path, data=_form(rendered.text, "clear"), follow_redirects=False)
        assert cleared.status_code == 303, cleared.text
        assert "本期尚未关联付款" in client.get(cleared.headers["location"]).text
        # Refreshing/retrying the original submitted form cannot relink after undo.
        replay = client.post(path, data=original, follow_redirects=False)
        assert replay.status_code == 303, replay.text
        current = client.get(replay.headers["location"])
        assert "本期尚未关联付款" in current.text
        assert client.get(
            f"/api/expenses/{payment['id']}", headers=identity.app_headers,
        ).json() == payment
    finally:
        app.dependency_overrides.pop(_require_local, None)
